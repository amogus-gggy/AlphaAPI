use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyByteArray, PyBytes, PyDict, PyFloat, PyInt, PyList, PyString, PyTuple,
};

/// Serialize a Python object to JSON bytes.
///
/// The common cases (dict, list, tuple, str, int, float, bool, None) are
/// encoded directly from the Python object graph into a pre-sized buffer.  This
/// avoids the `Python -> serde_json::Value -> bytes` round-trip (and its
/// intermediate allocations) that a generic serializer would perform.
///
/// Anything else (Pydantic models, dataclasses, enums, datetimes, ...) is
/// normalized once by `alphaapi._helpers.to_builtin` and encoded again.
pub fn json_bytes(py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<Vec<u8>> {
    let mut out = Vec::with_capacity(256);
    match write_json(obj, &mut out, 0) {
        Ok(()) => Ok(out),
        Err(first_error) => {
            let helpers = match py.import("alphaapi._helpers") {
                Ok(module) => module,
                Err(_) => return Err(first_error),
            };
            let converted = match helpers.call_method1("to_builtin", (obj,)) {
                Ok(converted) => converted,
                Err(_) => return Err(first_error),
            };
            out.clear();
            match write_json(&converted, &mut out, 0) {
                Ok(()) => Ok(out),
                Err(_) => Err(first_error),
            }
        }
    }
}

fn write_json(obj: &Bound<'_, PyAny>, out: &mut Vec<u8>, depth: usize) -> PyResult<()> {
    if depth > 128 {
        return Err(PyValueError::new_err(
            "JSON serialization too deeply nested",
        ));
    }

    if obj.is_none() {
        out.extend_from_slice(b"null");
        return Ok(());
    }

    // bool is a subclass of int, so it must be tested first.
    if obj.cast::<PyBool>().is_ok() {
        let value = obj.extract::<bool>()?;
        out.extend_from_slice(if value { b"true" } else { b"false" });
        return Ok(());
    }

    if let Ok(int) = obj.cast::<PyInt>() {
        match int.extract::<i64>() {
            Ok(value) => {
                let mut buffer = itoa::Buffer::new();
                out.extend_from_slice(buffer.format(value).as_bytes());
            }
            Err(_) => {
                // Arbitrarily large Python integers are valid JSON numbers.
                let text = int.str()?.to_string_lossy().into_owned();
                out.extend_from_slice(text.as_bytes());
            }
        }
        return Ok(());
    }

    if let Ok(float) = obj.cast::<PyFloat>() {
        let value = float.extract::<f64>()?;
        if value.is_finite() {
            let mut buffer = ryu::Buffer::new();
            out.extend_from_slice(buffer.format_finite(value).as_bytes());
        } else {
            out.extend_from_slice(b"null");
        }
        return Ok(());
    }

    if let Ok(text) = obj.cast::<PyString>() {
        write_json_string(out, &text.to_string_lossy());
        return Ok(());
    }

    if let Ok(dict) = obj.cast::<PyDict>() {
        out.push(b'{');
        let mut first = true;
        for (key, value) in dict.iter() {
            if !first {
                out.push(b',');
            }
            first = false;
            if let Ok(key) = key.cast::<PyString>() {
                write_json_string(out, &key.to_string_lossy());
            } else {
                // Match `json.dumps`: non-string keys are stringified.
                let key = key.str()?;
                write_json_string(out, &key.to_string_lossy());
            }
            out.push(b':');
            write_json(&value, out, depth + 1)?;
        }
        out.push(b'}');
        return Ok(());
    }

    if let Ok(list) = obj.cast::<PyList>() {
        out.push(b'[');
        for (index, value) in list.iter().enumerate() {
            if index != 0 {
                out.push(b',');
            }
            write_json(&value, out, depth + 1)?;
        }
        out.push(b']');
        return Ok(());
    }

    if let Ok(tuple) = obj.cast::<PyTuple>() {
        out.push(b'[');
        for (index, value) in tuple.iter().enumerate() {
            if index != 0 {
                out.push(b',');
            }
            write_json(&value, out, depth + 1)?;
        }
        out.push(b']');
        return Ok(());
    }

    Err(PyValueError::new_err(
        "object is not directly JSON serializable",
    ))
}

fn write_json_string(out: &mut Vec<u8>, value: &str) {
    out.push(b'"');
    let bytes = value.as_bytes();
    let mut start = 0;

    for (index, &byte) in bytes.iter().enumerate() {
        let escape: Option<&[u8]> = match byte {
            b'"' => Some(b"\\\""),
            b'\\' => Some(b"\\\\"),
            b'\n' => Some(b"\\n"),
            b'\r' => Some(b"\\r"),
            b'\t' => Some(b"\\t"),
            0x08 => Some(b"\\b"),
            0x0c => Some(b"\\f"),
            0x00..=0x1f => {
                if start < index {
                    out.extend_from_slice(&bytes[start..index]);
                }
                const HEX: &[u8; 16] = b"0123456789abcdef";
                out.extend_from_slice(b"\\u00");
                out.push(HEX[(byte >> 4) as usize]);
                out.push(HEX[(byte & 0x0f) as usize]);
                start = index + 1;
                None
            }
            _ => None,
        };

        if let Some(escape) = escape {
            if start < index {
                out.extend_from_slice(&bytes[start..index]);
            }
            out.extend_from_slice(escape);
            start = index + 1;
        }
    }

    if start < bytes.len() {
        out.extend_from_slice(&bytes[start..]);
    }
    out.push(b'"');
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

pub fn headers_to_vec(headers: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<(String, String)>> {
    let mut result = Vec::new();
    let Some(headers) = headers else {
        return Ok(result);
    };

    // Accept either a mapping (the common case) or an iterable of
    // ``(name, value)`` pairs, which can represent repeated headers such as
    // multiple ``Set-Cookie`` fields.
    if let Ok(dict) = headers.cast::<PyDict>() {
        for (key, value) in dict.iter() {
            result.push((key.extract::<String>()?, value.extract::<String>()?));
        }
        return Ok(result);
    }

    for item in headers.try_iter()? {
        let item = item?;
        let pair = item.cast::<PyTuple>().map_err(|_| {
            PyValueError::new_err("headers must be a mapping or an iterable of (name, value) pairs")
        })?;
        if pair.len() != 2 {
            return Err(PyValueError::new_err(
                "header pairs must contain exactly two items",
            ));
        }
        let key = pair.get_item(0)?;
        let value = pair.get_item(1)?;
        result.push((key.extract::<String>()?, value.extract::<String>()?));
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::write_json_string;

    #[test]
    fn json_strings_escape_control_characters_and_quotes() {
        let mut out = Vec::new();
        write_json_string(&mut out, "a\"b\\c\n\t\u{1}");
        assert_eq!(out, b"\"a\\\"b\\\\c\\n\\t\\u0001\"");
    }
}
