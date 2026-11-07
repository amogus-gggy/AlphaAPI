use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes, PyDict, PyString};

fn encode(_py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    let value: serde_json::Value = pythonize::depythonize(obj)?;
    serde_json::to_vec(&value).map_err(|e| PyValueError::new_err(e.to_string()))
}

/// Serialize a Python object to JSON bytes.
///
/// Fast paths (dict, list, tuple, str, int, float, bool, None) are handled
/// directly by `pythonize`. Anything else (Pydantic models, dataclasses,
/// enums, datetimes, ...) is normalized by `alphaapi._helpers.to_builtin`.
pub fn json_bytes(py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    match encode(py, obj) {
        Ok(bytes) => Ok(bytes),
        Err(first_error) => {
            let helpers = match py.import("alphaapi._helpers") {
                Ok(module) => module,
                Err(_) => return Err(first_error),
            };
            let converted = match helpers.call_method1("to_builtin", (obj,)) {
                Ok(converted) => converted,
                Err(_) => return Err(first_error),
            };
            encode(py, &converted)
        }
    }
}

/// Convert response content to bytes.
///
/// `str` becomes raw UTF-8 (not JSON-quoted), `bytes`/`bytearray` are passed
/// through, and everything else is JSON encoded.
pub fn content_to_bytes(py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    if let Ok(value) = obj.cast::<PyString>() {
        return Ok(value.to_string_lossy().into_owned().into_bytes());
    }
    if let Ok(value) = obj.cast::<PyBytes>() {
        return Ok(value.as_bytes().to_vec());
    }
    if let Ok(value) = obj.cast::<PyByteArray>() {
        return Ok(value.to_vec());
    }
    json_bytes(py, obj)
}

pub fn headers_to_vec(headers: Option<&Bound<'_, PyDict>>) -> PyResult<Vec<(String, String)>> {
    let mut result = Vec::new();
    if let Some(headers) = headers {
        for (key, value) in headers.iter() {
            result.push((key.extract::<String>()?, value.extract::<String>()?));
        }
    }
    Ok(result)
}
