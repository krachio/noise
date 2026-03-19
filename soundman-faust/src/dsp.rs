//! Safe wrapper around a compiled FAUST DSP instance (LLVM JIT).

#![allow(clippy::module_name_repetitions)]

use std::collections::HashMap;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_void};
use std::ptr;
use std::sync::Mutex;

use log::{debug, info};

use crate::ffi::{self, FaustFloat, UIGlue};

/// FAUST LLVM factory creation is not thread-safe. Serialize all compilation.
static COMPILE_LOCK: Mutex<()> = Mutex::new(());

/// Metadata for a single FAUST parameter discovered via `buildUserInterface`.
#[derive(Debug, Clone)]
pub struct ParamMeta {
    /// Parameter name as declared in FAUST (e.g. `"freq"`, `"gain"`).
    pub label: String,
    /// Raw pointer into the DSP instance's parameter memory.
    pub zone: *mut FaustFloat,
    /// Default value.
    pub init: f32,
    /// Minimum allowed value.
    pub min: f32,
    /// Maximum allowed value.
    pub max: f32,
    /// UI step size hint.
    pub step: f32,
}

// SAFETY: zone pointers belong to the DSP instance which we ensure is only
// accessed from one thread at a time (Send but not Sync).
unsafe impl Send for ParamMeta {}

/// A compiled FAUST DSP — owns both the factory and instance pointers.
///
/// Not `Sync` because `computeCDSPInstance` mutates internal state.
pub struct FaustDsp {
    factory: *mut ffi::llvm_dsp_factory,
    dsp: *mut ffi::llvm_dsp,
    num_inputs: usize,
    num_outputs: usize,
    params: HashMap<String, ParamMeta>,
    /// Scratch input buffer pointers (one per FAUST input channel).
    input_ptrs: Vec<*mut FaustFloat>,
    /// Scratch output buffer pointers (one per FAUST output channel).
    output_ptrs: Vec<*mut FaustFloat>,
    /// Owned scratch buffers for FAUST input channels.
    input_bufs: Vec<Vec<FaustFloat>>,
    /// Owned scratch buffers for FAUST output channels.
    output_bufs: Vec<Vec<FaustFloat>>,
}

// SAFETY: The FAUST C API is not thread-safe for a single instance, but
// instances can be used from different threads as long as one thread at a time
// accesses an instance. Send is fine; Sync is not.
unsafe impl Send for FaustDsp {}

impl FaustDsp {
    /// Compile FAUST DSP code via LLVM JIT and create an initialized instance.
    ///
    /// # Errors
    /// Returns a string describing the compilation error if FAUST rejects the code.
    #[allow(clippy::cast_sign_loss)]
    pub fn from_code(
        name: &str,
        code: &str,
        sample_rate: u32,
        block_size: usize,
    ) -> Result<Self, String> {
        let c_name = CString::new(name).map_err(|e| e.to_string())?;
        let c_code = CString::new(code).map_err(|e| e.to_string())?;
        let c_target = CString::new("").map_err(|e| e.to_string())?;
        let mut error_buf = vec![0u8; 4096];

        // FAUST LLVM factory creation is not thread-safe — serialize it.
        let guard = COMPILE_LOCK.lock().map_err(|e| e.to_string())?;

        // SAFETY: calling FAUST C API with valid CString pointers
        let factory = unsafe {
            ffi::createCDSPFactoryFromString(
                c_name.as_ptr(),
                c_code.as_ptr(),
                0,
                ptr::null(),
                c_target.as_ptr(),
                error_buf.as_mut_ptr().cast::<c_char>(),
                -1, // max optimization
            )
        };

        if factory.is_null() {
            // SAFETY: error_buf was zeroed, FAUST writes a null-terminated string
            let err = unsafe { CStr::from_ptr(error_buf.as_ptr().cast::<c_char>()) };
            return Err(format!(
                "FAUST compilation failed: {}",
                err.to_string_lossy()
            ));
        }

        // SAFETY: factory is non-null, returned by FAUST
        let dsp = unsafe { ffi::createCDSPInstance(factory) };
        if dsp.is_null() {
            unsafe { ffi::deleteCDSPFactory(factory) };
            return Err("failed to create FAUST DSP instance".into());
        }

        drop(guard);

        // SAFETY: dsp is non-null
        unsafe {
            ffi::initCDSPInstance(dsp, c_int::try_from(sample_rate).unwrap_or(44100));
        }

        let num_inputs = unsafe { ffi::getNumInputsCDSPInstance(dsp) } as usize;
        let num_outputs = unsafe { ffi::getNumOutputsCDSPInstance(dsp) } as usize;

        info!("FAUST '{name}': {num_inputs} in, {num_outputs} out, {sample_rate}Hz");

        let params = discover_params(dsp);
        for (label, meta) in &params {
            debug!(
                "  param '{label}': init={}, range=[{}, {}], step={}",
                meta.init, meta.min, meta.max, meta.step
            );
        }

        let input_bufs: Vec<Vec<FaustFloat>> = (0..num_inputs)
            .map(|_| vec![0.0; block_size])
            .collect();
        let output_bufs: Vec<Vec<FaustFloat>> = (0..num_outputs)
            .map(|_| vec![0.0; block_size])
            .collect();
        let input_ptrs = Vec::with_capacity(num_inputs);
        let output_ptrs = Vec::with_capacity(num_outputs);

        Ok(Self {
            factory,
            dsp,
            num_inputs,
            num_outputs,
            params,
            input_ptrs,
            output_ptrs,
            input_bufs,
            output_bufs,
        })
    }

    /// Number of audio input channels.
    #[must_use]
    pub const fn num_inputs(&self) -> usize {
        self.num_inputs
    }

    /// Number of audio output channels.
    #[must_use]
    pub const fn num_outputs(&self) -> usize {
        self.num_outputs
    }

    /// Discovered parameters, keyed by label.
    #[must_use]
    #[allow(clippy::missing_const_for_fn)]
    pub fn params(&self) -> &HashMap<String, ParamMeta> {
        &self.params
    }

    /// Set a parameter by label. Returns false if parameter not found.
    pub fn set_param(&mut self, label: &str, value: f32) -> bool {
        self.params.get(label).is_some_and(|meta| {
            let clamped = value.clamp(meta.min, meta.max);
            // SAFETY: zone points into the live DSP instance memory
            unsafe { *meta.zone = clamped };
            true
        })
    }

    /// Process audio. Reads from `inputs` (one slice per FAUST input channel),
    /// writes to `outputs` (one slice per FAUST output channel).
    ///
    /// If the DSP has 0 inputs (generator), `inputs` can be empty.
    #[allow(clippy::cast_possible_truncation, clippy::cast_possible_wrap)]
    pub fn compute(&mut self, inputs: &[&[f32]], outputs: &mut [&mut [f32]]) {
        if outputs.is_empty() {
            return;
        }
        let count = outputs[0].len();

        // Build input pointer array
        self.input_ptrs.clear();
        for (i, buf) in self.input_bufs.iter_mut().enumerate() {
            if buf.len() < count {
                buf.resize(count, 0.0);
            }
            if i < inputs.len() {
                buf[..count].copy_from_slice(&inputs[i][..count]);
            } else {
                buf[..count].fill(0.0);
            }
            self.input_ptrs.push(buf.as_mut_ptr());
        }

        // Build output pointer array
        self.output_ptrs.clear();
        for buf in &mut self.output_bufs {
            if buf.len() < count {
                buf.resize(count, 0.0);
            }
            buf[..count].fill(0.0);
            self.output_ptrs.push(buf.as_mut_ptr());
        }

        // SAFETY: pointers are valid, count matches buffer lengths
        unsafe {
            ffi::computeCDSPInstance(
                self.dsp,
                count as c_int,
                self.input_ptrs.as_mut_ptr(),
                self.output_ptrs.as_mut_ptr(),
            );
        }

        // Copy FAUST output buffers into caller's output slices
        for (i, out_slice) in outputs.iter_mut().enumerate() {
            if i < self.output_bufs.len() {
                out_slice[..count].copy_from_slice(&self.output_bufs[i][..count]);
            }
        }
    }

    /// Re-initialize the DSP at a new sample rate.
    #[allow(clippy::cast_possible_truncation, clippy::cast_possible_wrap)]
    pub fn reset(&mut self, sample_rate: u32) {
        // SAFETY: dsp is valid
        unsafe {
            ffi::initCDSPInstance(self.dsp, sample_rate as c_int);
        }
        // Re-discover params (zone pointers may change after re-init)
        self.params = discover_params(self.dsp);
    }
}

impl Drop for FaustDsp {
    fn drop(&mut self) {
        // SAFETY: we own both the instance and factory
        unsafe {
            ffi::deleteCDSPInstance(self.dsp);
            ffi::deleteCDSPFactory(self.factory);
        }
    }
}

impl std::fmt::Debug for FaustDsp {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FaustDsp")
            .field("num_inputs", &self.num_inputs)
            .field("num_outputs", &self.num_outputs)
            .field("params", &self.params.keys().collect::<Vec<_>>())
            .finish_non_exhaustive()
    }
}

// ---- UIGlue parameter discovery ----

struct ParamCollector {
    params: HashMap<String, ParamMeta>,
}

fn discover_params(dsp: *mut ffi::llvm_dsp) -> HashMap<String, ParamMeta> {
    let mut collector = ParamCollector {
        params: HashMap::new(),
    };

    let mut glue = UIGlue {
        ui_interface: (&raw mut collector).cast::<c_void>(),
        open_tab_box: Some(ui_noop_open),
        open_horizontal_box: Some(ui_noop_open),
        open_vertical_box: Some(ui_noop_open),
        close_box: Some(ui_noop_close),
        add_button: Some(ui_add_button),
        add_check_button: Some(ui_add_button),
        add_vertical_slider: Some(ui_add_slider),
        add_horizontal_slider: Some(ui_add_slider),
        add_num_entry: Some(ui_add_slider),
        add_horizontal_bargraph: Some(ui_add_bargraph),
        add_vertical_bargraph: Some(ui_add_bargraph),
        add_soundfile: Some(ui_add_soundfile),
        declare: Some(ui_declare),
    };

    // SAFETY: glue is valid, dsp is valid
    unsafe {
        ffi::buildUserInterfaceCDSPInstance(dsp, &raw mut glue);
    }

    collector.params
}

// ---- UIGlue callback implementations ----
// These are extern "C" callbacks invoked by FAUST's buildUserInterface.

const unsafe extern "C" fn ui_noop_open(_ui: *mut c_void, _label: *const c_char) {}
const unsafe extern "C" fn ui_noop_close(_ui: *mut c_void) {}

unsafe extern "C" fn ui_add_button(
    ui: *mut c_void,
    label: *const c_char,
    zone: *mut FaustFloat,
) {
    // SAFETY: ui points to our ParamCollector, label is a valid C string from FAUST
    let collector = unsafe { &mut *ui.cast::<ParamCollector>() };
    let label_str = unsafe { CStr::from_ptr(label) }
        .to_string_lossy()
        .into_owned();
    collector.params.insert(
        label_str.clone(),
        ParamMeta {
            label: label_str,
            zone,
            init: 0.0,
            min: 0.0,
            max: 1.0,
            step: 1.0,
        },
    );
}

#[allow(clippy::too_many_arguments)]
unsafe extern "C" fn ui_add_slider(
    ui: *mut c_void,
    label: *const c_char,
    zone: *mut FaustFloat,
    init: FaustFloat,
    min: FaustFloat,
    max: FaustFloat,
    step: FaustFloat,
) {
    // SAFETY: ui points to our ParamCollector, label is a valid C string from FAUST
    let collector = unsafe { &mut *ui.cast::<ParamCollector>() };
    let label_str = unsafe { CStr::from_ptr(label) }
        .to_string_lossy()
        .into_owned();
    collector.params.insert(
        label_str.clone(),
        ParamMeta {
            label: label_str,
            zone,
            init,
            min,
            max,
            step,
        },
    );
}

const unsafe extern "C" fn ui_add_bargraph(
    _ui: *mut c_void,
    _label: *const c_char,
    _zone: *mut FaustFloat,
    _min: FaustFloat,
    _max: FaustFloat,
) {
}

const unsafe extern "C" fn ui_add_soundfile(
    _ui: *mut c_void,
    _label: *const c_char,
    _url: *const c_char,
    _sf_zone: *mut *mut ffi::Soundfile,
) {
}

const unsafe extern "C" fn ui_declare(
    _ui: *mut c_void,
    _zone: *mut FaustFloat,
    _key: *const c_char,
    _value: *const c_char,
) {
}
