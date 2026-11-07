mod app;
mod request;
mod response;
mod spec;
mod util;

use pyo3::prelude::*;

#[pymodule]
fn _core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<app::AppCore>()?;
    module.add_class::<request::Request>()?;
    module.add_class::<response::Response>()?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
