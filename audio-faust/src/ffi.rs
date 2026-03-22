//! Raw FFI bindings to the FAUST LLVM JIT C API.
//!
//! Corresponds to `faust/dsp/llvm-dsp-c.h` and `faust/gui/CInterface.h`.

#![allow(non_camel_case_types, clippy::doc_markdown)]

use std::os::raw::{c_char, c_float, c_int, c_void};

/// Opaque FAUST DSP factory handle.
#[repr(C)]
pub struct llvm_dsp_factory {
    _opaque: [u8; 0],
}

/// Opaque FAUST DSP instance handle.
#[repr(C)]
pub struct llvm_dsp {
    _opaque: [u8; 0],
}

/// Soundfile placeholder (unused but referenced by UIGlue).
#[repr(C)]
pub struct Soundfile {
    _opaque: [u8; 0],
}

/// FAUSTFLOAT matches the C default: float.
pub type FaustFloat = c_float;

// -- UIGlue function pointer types --

pub type OpenTabBoxFn = Option<unsafe extern "C" fn(*mut c_void, *const c_char)>;
pub type OpenHorizontalBoxFn = Option<unsafe extern "C" fn(*mut c_void, *const c_char)>;
pub type OpenVerticalBoxFn = Option<unsafe extern "C" fn(*mut c_void, *const c_char)>;
pub type CloseBoxFn = Option<unsafe extern "C" fn(*mut c_void)>;

pub type AddButtonFn = Option<unsafe extern "C" fn(*mut c_void, *const c_char, *mut FaustFloat)>;
pub type AddCheckButtonFn =
    Option<unsafe extern "C" fn(*mut c_void, *const c_char, *mut FaustFloat)>;

pub type AddSliderFn = Option<
    unsafe extern "C" fn(
        *mut c_void,
        *const c_char,
        *mut FaustFloat,
        FaustFloat,
        FaustFloat,
        FaustFloat,
        FaustFloat,
    ),
>;

pub type AddBargraphFn = Option<
    unsafe extern "C" fn(*mut c_void, *const c_char, *mut FaustFloat, FaustFloat, FaustFloat),
>;

pub type AddSoundfileFn =
    Option<unsafe extern "C" fn(*mut c_void, *const c_char, *const c_char, *mut *mut Soundfile)>;

pub type DeclareFn =
    Option<unsafe extern "C" fn(*mut c_void, *mut FaustFloat, *const c_char, *const c_char)>;

/// Mirror of C `UIGlue` struct — function pointers for parameter discovery.
#[repr(C)]
pub struct UIGlue {
    pub ui_interface: *mut c_void,
    pub open_tab_box: OpenTabBoxFn,
    pub open_horizontal_box: OpenHorizontalBoxFn,
    pub open_vertical_box: OpenVerticalBoxFn,
    pub close_box: CloseBoxFn,
    pub add_button: AddButtonFn,
    pub add_check_button: AddCheckButtonFn,
    pub add_vertical_slider: AddSliderFn,
    pub add_horizontal_slider: AddSliderFn,
    pub add_num_entry: AddSliderFn,
    pub add_horizontal_bargraph: AddBargraphFn,
    pub add_vertical_bargraph: AddBargraphFn,
    pub add_soundfile: AddSoundfileFn,
    pub declare: DeclareFn,
}

/// Mirror of C `MetaGlue` struct.
#[repr(C)]
#[allow(dead_code)]
pub struct MetaGlue {
    pub meta_interface: *mut c_void,
    pub declare: Option<unsafe extern "C" fn(*mut c_void, *const c_char, *const c_char)>,
}

#[allow(dead_code)]
unsafe extern "C" {
    // -- Factory lifecycle --

    pub fn getCLibFaustVersion() -> *const c_char;

    pub fn createCDSPFactoryFromString(
        name_app: *const c_char,
        dsp_content: *const c_char,
        argc: c_int,
        argv: *const *const c_char,
        target: *const c_char,
        error_msg: *mut c_char,
        opt_level: c_int,
    ) -> *mut llvm_dsp_factory;

    pub fn deleteCDSPFactory(factory: *mut llvm_dsp_factory) -> bool;

    pub fn deleteAllCDSPFactories();

    // -- Instance lifecycle --

    pub fn createCDSPInstance(factory: *mut llvm_dsp_factory) -> *mut llvm_dsp;

    pub fn deleteCDSPInstance(dsp: *mut llvm_dsp);

    pub fn initCDSPInstance(dsp: *mut llvm_dsp, sample_rate: c_int);

    pub fn getNumInputsCDSPInstance(dsp: *mut llvm_dsp) -> c_int;

    pub fn getNumOutputsCDSPInstance(dsp: *mut llvm_dsp) -> c_int;

    pub fn computeCDSPInstance(
        dsp: *mut llvm_dsp,
        count: c_int,
        inputs: *mut *mut FaustFloat,
        outputs: *mut *mut FaustFloat,
    );

    pub fn buildUserInterfaceCDSPInstance(dsp: *mut llvm_dsp, ui: *mut UIGlue);

    pub fn cloneCDSPInstance(dsp: *mut llvm_dsp) -> *mut llvm_dsp;

    // -- Memory --

    pub fn freeCMemory(ptr: *mut c_void);
}
