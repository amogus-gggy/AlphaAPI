use pyo3::prelude::*;
use pyo3::types::PyDict;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ParamKind {
    Path,
    Query,
    Header,
    Body,
    Request,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TypeKind {
    Str,
    Int,
    Float,
    Bool,
    StrList,
    Json,
    Model,
    Bytes,
}

pub struct ParamSpec {
    pub name: String,
    pub kind: ParamKind,
    pub ty: TypeKind,
    pub required: bool,
    pub default: Option<Py<PyAny>>,
    pub model: Option<Py<PyAny>>,
    pub positional: bool,
    pub alias: String,
}

pub struct RouteSpec {
    pub params: Vec<ParamSpec>,
    pub is_async: bool,
    pub status_code: u16,
    pub needs_request: bool,
    pub has_body: bool,
    pub has_header_params: bool,
    pub has_query_params: bool,
    pub has_path_params: bool,
}

fn opt_str<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Option<String>> {
    match dict.get_item(key)? {
        Some(item) if !item.is_none() => Ok(Some(item.extract()?)),
        _ => Ok(None),
    }
}

fn req_str(dict: &Bound<'_, PyDict>, key: &str, what: &str) -> PyResult<String> {
    opt_str(dict, key)?
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err(format!("missing {what}")))
}

fn req_bool(dict: &Bound<'_, PyDict>, key: &str, default: bool) -> PyResult<bool> {
    match dict.get_item(key)? {
        Some(item) if !item.is_none() => Ok(item.extract()?),
        _ => Ok(default),
    }
}

fn parse_kind(value: &str) -> PyResult<ParamKind> {
    Ok(match value {
        "path" => ParamKind::Path,
        "query" => ParamKind::Query,
        "header" => ParamKind::Header,
        "body" => ParamKind::Body,
        "request" => ParamKind::Request,
        other => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown parameter kind: {other}"
            )))
        }
    })
}

fn parse_type(value: &str) -> PyResult<TypeKind> {
    Ok(match value {
        "str" => TypeKind::Str,
        "int" => TypeKind::Int,
        "float" => TypeKind::Float,
        "bool" => TypeKind::Bool,
        "str_list" => TypeKind::StrList,
        "json" => TypeKind::Json,
        "model" => TypeKind::Model,
        "bytes" => TypeKind::Bytes,
        "request" => TypeKind::Str,
        other => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "unknown parameter type: {other}"
            )))
        }
    })
}

impl RouteSpec {
    pub fn from_py(py: Python<'_>, spec: &Bound<'_, PyDict>) -> PyResult<Self> {
        let params_obj = spec
            .get_item("params")?
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("spec.params is required"))?;
        let params_list = params_obj.cast::<pyo3::types::PyList>()?;

        let mut params = Vec::with_capacity(params_list.len());
        for item in params_list.iter() {
            let dict = item.cast::<PyDict>()?;
            let name = req_str(dict, "name", "parameter name")?;
            let kind = parse_kind(&req_str(dict, "kind", "parameter kind")?)?;
            let ty = parse_type(&req_str(dict, "type", "parameter type")?)?;
            let required = req_bool(dict, "required", false)?;
            let positional = req_bool(dict, "positional", true)?;
            let mut alias = opt_str(dict, "alias")?.unwrap_or_else(|| name.clone());
            if kind == ParamKind::Header {
                // Header lookups in `HeaderMap` use lowercase names.  Doing this
                // once here avoids allocating on every request.
                alias = alias.to_ascii_lowercase();
            }

            let default = match dict.get_item("default")? {
                Some(value) if !required => Some(value.unbind()),
                _ => None,
            };
            let model = match dict.get_item("model")? {
                Some(value) if !value.is_none() => Some(value.unbind()),
                _ => None,
            };

            params.push(ParamSpec {
                name,
                kind,
                ty,
                required,
                default,
                model,
                positional,
                alias,
            });
        }

        let is_async = req_bool(spec, "is_async", false)?;
        let status_code = match spec.get_item("status_code")? {
            Some(value) if !value.is_none() => value.extract()?,
            _ => 200,
        };
        let needs_request = params.iter().any(|p| p.kind == ParamKind::Request);
        let has_body = params.iter().any(|p| p.kind == ParamKind::Body);
        let has_header_params = params.iter().any(|p| p.kind == ParamKind::Header);
        let has_query_params = params.iter().any(|p| p.kind == ParamKind::Query);
        let has_path_params = params.iter().any(|p| p.kind == ParamKind::Path);

        let _ = py;
        Ok(RouteSpec {
            params,
            is_async,
            status_code,
            needs_request,
            has_body,
            has_header_params,
            has_query_params,
            has_path_params,
        })
    }
}
