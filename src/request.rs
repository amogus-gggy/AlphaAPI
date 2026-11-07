use std::collections::HashMap;

use bytes::Bytes;
use http::{HeaderMap, Method};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyString};

/// An incoming HTTP request.
///
/// Instances are created by the Rust core and injected into handlers that
/// declare a parameter annotated with `alphaapi.Request`.
#[pyclass(frozen, module = "alphaapi._core")]
pub struct Request {
    pub method: Method,
    pub path: String,
    pub query_string: String,
    pub client: Option<String>,
    pub headers: HeaderMap,
    pub params: Vec<(String, String)>,
    pub query: HashMap<String, Vec<String>>,
    /// The raw body is stored as reference-counted `Bytes` so that cloning it
    /// (e.g. for the injected request object) never copies the payload.
    pub raw_body: Bytes,
}

impl Request {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        method: Method,
        path: String,
        query_string: String,
        client: Option<String>,
        headers: HeaderMap,
        params: Vec<(String, String)>,
        query: HashMap<String, Vec<String>>,
        raw_body: Bytes,
    ) -> Self {
        Self {
            method,
            path,
            query_string,
            client,
            headers,
            params,
            query,
            raw_body,
        }
    }
}

#[pymethods]
impl Request {
    #[getter]
    fn method(&self) -> String {
        self.method.as_str().to_string()
    }

    #[getter]
    fn path(&self) -> String {
        self.path.clone()
    }

    #[getter]
    fn query_string(&self) -> String {
        self.query_string.clone()
    }

    #[getter]
    fn client(&self) -> Option<String> {
        self.client.clone()
    }

    /// All request headers, with lowercase keys.  Repeated headers are joined
    /// with `", "` to match common HTTP semantics.
    #[getter]
    fn headers<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (name, value) in &self.headers {
            let key = name.as_str();
            let value = value.to_str().unwrap_or("");
            match dict.get_item(key)? {
                Some(existing) => {
                    let joined = format!("{}, {}", existing.extract::<String>()?, value);
                    dict.set_item(key, joined)?;
                }
                None => {
                    dict.set_item(key, value)?;
                }
            }
        }
        Ok(dict)
    }

    /// Path parameters extracted from the matched route.
    #[getter]
    fn params<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (key, value) in &self.params {
            dict.set_item(key, value)?;
        }
        Ok(dict)
    }

    /// All query parameters. Keys with multiple values map to lists.
    #[getter]
    fn query_params<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (key, values) in &self.query {
            if values.len() == 1 {
                dict.set_item(key, &values[0])?;
            } else {
                dict.set_item(key, values)?;
            }
        }
        Ok(dict)
    }

    /// The raw request body.
    #[getter]
    fn body<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.raw_body)
    }

    /// Decode the body as UTF-8 text.
    fn text(&self) -> String {
        String::from_utf8_lossy(&self.raw_body).into_owned()
    }

    /// Parse the body as JSON.
    fn json(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let value: serde_json::Value = serde_json::from_slice(&self.raw_body)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
        Ok(pythonize::pythonize(py, &value)?.unbind())
    }

    /// Look up a single header by name (case-insensitive).
    #[pyo3(signature = (name, default = None))]
    fn header(&self, py: Python<'_>, name: &str, default: Option<Py<PyAny>>) -> Py<PyAny> {
        match self.headers.get(name) {
            Some(value) => PyString::new(py, value.to_str().unwrap_or(""))
                .into_any()
                .unbind(),
            None => default.unwrap_or_else(|| py.None()),
        }
    }

    /// Look up a single query parameter by name.
    #[pyo3(signature = (name, default = None))]
    fn query_param(&self, py: Python<'_>, name: &str, default: Option<Py<PyAny>>) -> Py<PyAny> {
        match self.query.get(name).and_then(|values| values.last()) {
            Some(value) => PyString::new(py, value).into_any().unbind(),
            None => default.unwrap_or_else(|| py.None()),
        }
    }

    fn __repr__(&self) -> String {
        format!("<Request {} {}>", self.method, self.path)
    }
}
