use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

use crate::util::{content_to_bytes, headers_to_vec};

/// A full HTTP response.
///
/// Returning a `Response` from a handler bypasses automatic serialization.
/// The higher-level `JSONResponse`, `PlainTextResponse`, `HTMLResponse` and
/// `RedirectResponse` classes build on top of this type.
#[pyclass(subclass, module = "alphaapi._core")]
pub struct Response {
    pub status_code: u16,
    pub body: Vec<u8>,
    pub headers: Vec<(String, String)>,
    pub media_type: Option<String>,
}

impl Response {
    /// Clone the fields out of a Python `Response` (including subclasses).
    pub fn from_instance(obj: &Bound<'_, PyAny>) -> Option<Response> {
        let instance = obj.cast::<Response>().ok()?;
        let borrowed = instance.try_borrow().ok()?;
        Some(Response {
            status_code: borrowed.status_code,
            body: borrowed.body.clone(),
            headers: borrowed.headers.clone(),
            media_type: borrowed.media_type.clone(),
        })
    }
}

#[pymethods]
impl Response {
    #[new]
    #[pyo3(signature = (content = None, status_code = 200, headers = None, media_type = None))]
    fn new(
        py: Python<'_>,
        content: Option<&Bound<'_, PyAny>>,
        status_code: u16,
        headers: Option<&Bound<'_, PyDict>>,
        media_type: Option<String>,
    ) -> PyResult<Self> {
        let body = match content {
            Some(value) if !value.is_none() => content_to_bytes(py, value)?,
            _ => Vec::new(),
        };
        Ok(Self {
            status_code,
            body,
            headers: headers_to_vec(headers)?,
            media_type,
        })
    }

    #[getter]
    fn status_code(&self) -> u16 {
        self.status_code
    }

    #[setter]
    fn set_status_code(&mut self, value: u16) {
        self.status_code = value;
    }

    #[getter]
    fn headers<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let dict = PyDict::new(py);
        for (key, value) in &self.headers {
            dict.set_item(key, value)?;
        }
        Ok(dict)
    }

    #[setter]
    fn set_headers(&mut self, headers: &Bound<'_, PyDict>) -> PyResult<()> {
        self.headers = headers_to_vec(Some(headers))?;
        Ok(())
    }

    #[getter]
    fn body<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.body)
    }

    #[setter]
    fn set_body(&mut self, py: Python<'_>, content: &Bound<'_, PyAny>) -> PyResult<()> {
        self.body = content_to_bytes(py, content)?;
        Ok(())
    }

    #[getter]
    fn media_type(&self) -> Option<String> {
        self.media_type.clone()
    }

    #[setter]
    fn set_media_type(&mut self, media_type: Option<String>) {
        self.media_type = media_type;
    }

    fn __repr__(&self) -> String {
        format!(
            "<Response status_code={} content_type={:?} length={}>",
            self.status_code,
            self.media_type,
            self.body.len()
        )
    }
}
