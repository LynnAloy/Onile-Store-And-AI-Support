"""Focused OpenAPI response checks used by real payment smoke tests (no external dependencies).

Checks refs, oneOf, nullable, required/extra fields, JSON types, enums, bounds and patterns.
This is deliberately not a full OpenAPI validator; format annotations are not checked.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DOCUMENT = json.loads((ROOT / "docs/m51-payment.openapi.json").read_text(encoding="utf-8"))


def validate(value, schema):
    if "$ref" in schema:
        target = DOCUMENT
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return validate(value, target)
    if value is None and schema.get("nullable"):
        return
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                validate(value, option)
                matches += 1
            except AssertionError:
                pass
        assert matches == 1, "Response must match exactly one schema"
        return
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind in types:
        assert type(value) is types[kind], "Response JSON type mismatch: " + kind
    if "enum" in schema:
        assert value in schema["enum"], "Response enum mismatch"
    if kind == "object":
        assert set(schema.get("required", [])) <= value.keys(), "Response missing required fields"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert value.keys() <= properties.keys(), "Response contains undeclared fields"
        for key in value.keys() & properties.keys():
            validate(value[key], properties[key])
    if kind == "array":
        assert schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", float("inf")), "Response array bounds"
        for item in value:
            validate(item, schema["items"])
    if kind == "string":
        assert schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", float("inf")), "Response string bounds"
        if "pattern" in schema:
            assert re.fullmatch(schema["pattern"], value), "Response pattern mismatch"
    if kind == "integer":
        assert schema.get("minimum", -float("inf")) <= value <= schema.get("maximum", float("inf")), "Response numeric bounds"


def operation(method, path):
    path = urlsplit(path).path
    for template, methods in DOCUMENT["paths"].items():
        pattern = re.sub(r"\{[^}]+\}", "[^/]+", template)
        if re.fullmatch(pattern, path):
            return methods.get(method.lower())
    return None


def response(method, path, status, body, headers):
    op = operation(method, path)
    assert op is not None
    assert headers.get("Cache-Control") == "no-store", "Unexpected Cache-Control: " + str(headers.get("Cache-Control"))
    spec = op["responses"].get(str(status)) or op["responses"].get("default")
    assert spec is not None, "Undocumented HTTP response status"
    if "$ref" in spec:
        target = DOCUMENT
        for part in spec["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        spec = target
    validate(body, spec["content"]["application/json"]["schema"])
