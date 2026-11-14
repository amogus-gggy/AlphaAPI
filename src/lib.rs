mod app;
mod request;
mod response;
mod spec;
mod util;

use pyo3::prelude::*;
use pyo3::types::{PyAny, PyBytes};

/// Serialize a Python value to JSON bytes using the Rust encoder.
///
/// This is exposed so higher-level response helpers (such as
/// ``JsonResponse``) can avoid ``json.dumps`` on the hot path.
#[pyfunction]
fn dumps(py: Python<'_>, value: &Bound<'_, PyAny>) -> PyResult<Py<PyBytes>> {
    let bytes = util::json_bytes(py, value)?;
    Ok(PyBytes::new(py, &bytes).unbind())
}

#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<app::AppCore>()?;
    module.add_class::<request::Request>()?;
    module.add_class::<response::Response>()?;
    module.add_function(wrap_pyfunction!(dumps, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
