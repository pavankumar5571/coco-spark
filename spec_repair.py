"""Bounded, auditable repair for Gemini-produced structured specifications.

The module owns no network client. A production caller may inject a provider exposing
``repair(document, errors, allowed_paths)``; tests inject a fake. Every accepted document
passes the same shape and semantic validators, including deterministic fallbacks.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re


def _pointer(parts):
    return "/" + "/".join(str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def schema_errors(value, schema, parts=()):
    """Validate the dependency-free JSON-Schema subset emitted by schema.py."""
    errors = []
    expected = schema.get("type")
    kinds = {"object": dict, "array": list, "string": str,
             "integer": int, "number": (int, float), "boolean": bool}
    if expected in kinds:
        valid = isinstance(value, kinds[expected])
        if expected in {"integer", "number"} and isinstance(value, bool):
            valid = False
        if not valid:
            return [{"code": "TYPE", "path": _pointer(parts),
                     "message": f"expected {expected}"}]
    if "enum" in schema and value not in schema["enum"]:
        errors.append({"code": "ENUM", "path": _pointer(parts),
                       "message": f"value is not in {schema['enum']}"})
    if expected == "object":
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append({"code": "REQUIRED", "path": _pointer(parts + (key,)),
                               "message": "required value is missing"})
        for key, child in value.items():
            if key in properties:
                errors.extend(schema_errors(child, properties[key], parts + (key,)))
    elif expected == "array" and "items" in schema:
        for index, child in enumerate(value):
            errors.extend(schema_errors(child, schema["items"], parts + (index,)))
    return errors


def _get(document, pointer):
    node = document
    for raw in pointer.strip("/").split("/") if pointer != "/" else []:
        key = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node


def _set(document, pointer, value, *, must_exist=False):
    tokens = pointer.strip("/").split("/")
    if not tokens or tokens == [""]:
        raise ValueError("root replacement is forbidden")
    node = document
    for raw in tokens[:-1]:
        key = raw.replace("~1", "/").replace("~0", "~")
        node = node[int(key)] if isinstance(node, list) else node[key]
    key = tokens[-1].replace("~1", "/").replace("~0", "~")
    if isinstance(node, list):
        index = int(key)
        if must_exist and index >= len(node): raise KeyError(pointer)
        if index == len(node): node.append(deepcopy(value))
        else: node[index] = deepcopy(value)
    else:
        if must_exist and key not in node: raise KeyError(pointer)
        node[key] = deepcopy(value)


def _parse(candidate):
    if isinstance(candidate, dict):
        return deepcopy(candidate), False
    if not isinstance(candidate, str):
        raise ValueError("candidate must be an object or JSON string")
    text = candidate.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.I | re.S)
    if fenced:
        text = fenced.group(1)
    return json.loads(text), bool(fenced)


def _hash(document):
    data = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def validate_document(document, schema, semantic_validator):
    errors = schema_errors(document, schema)
    if not errors:
        errors.extend(semantic_validator(document) or [])
    return sorted(errors, key=lambda x: (x.get("path", ""), x.get("code", "")))


def repair_spec(candidate, *, schema, semantic_validator=lambda _: [], provider=None,
                aliases=None, defaults=None, immutable_paths=(), max_model_attempts=1,
                fallback_factory=None):
    """Return a verdict, accepted document (if any), and complete attempt manifest."""
    manifest = []
    try:
        document, unfenced = _parse(candidate)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"status": "UNRECOVERABLE", "document": None,
                "manifest": [{"stage": "PARSE", "errors": [{"code": "INVALID_JSON",
                              "path": "/", "message": str(exc)}]}]}

    errors = validate_document(document, schema, semantic_validator)
    manifest.append({"stage": "INPUT", "sha256": _hash(document), "errors": errors})
    if not errors:
        return {"status": "VALID_DETERMINISTIC" if unfenced else "VALID_ORIGINAL",
                "document": document, "manifest": manifest}

    changed = unfenced
    for path, mapping in (aliases or {}).items():
        try: current = _get(document, path)
        except (KeyError, IndexError, TypeError, ValueError): continue
        if current in mapping:
            _set(document, path, mapping[current], must_exist=True); changed = True
    for path, value in (defaults or {}).items():
        try: _get(document, path)
        except (KeyError, IndexError, TypeError, ValueError):
            try: _set(document, path, value)
            except (KeyError, IndexError, TypeError, ValueError): continue
            changed = True
    if changed:
        errors = validate_document(document, schema, semantic_validator)
        manifest.append({"stage": "DETERMINISTIC", "sha256": _hash(document),
                         "errors": errors})
        if not errors:
            return {"status": "VALID_DETERMINISTIC", "document": document,
                    "manifest": manifest}

    for attempt in range(max(0, max_model_attempts)):
        if provider is None: break
        allowed = sorted({error["path"] for error in errors})
        patches = provider.repair(deepcopy(document), deepcopy(errors), allowed)
        rejected = []
        for patch in patches if isinstance(patches, list) else []:
            path, operation = patch.get("path"), patch.get("op")
            immutable = any(path == root or path.startswith(root + "/")
                            for root in immutable_paths) if isinstance(path, str) else True
            if operation not in {"add", "replace"} or path not in allowed or immutable:
                rejected.append({"code": "PATCH_FORBIDDEN", "path": path or "/",
                                 "message": "patch operation/path is outside rejected fields"})
                continue
            try:
                _set(document, path, patch.get("value"), must_exist=operation == "replace")
            except (KeyError, IndexError, TypeError, ValueError):
                rejected.append({"code": "PATCH_INVALID", "path": path,
                                 "message": "patch target does not match document"})
        errors = rejected or validate_document(document, schema, semantic_validator)
        manifest.append({"stage": "MODEL_REPAIR", "attempt": attempt + 1,
                         "sha256": _hash(document), "errors": errors})
        if not errors:
            return {"status": "VALID_MODEL_REPAIR", "document": document,
                    "manifest": manifest}

    if fallback_factory is not None:
        fallback = fallback_factory(deepcopy(document), deepcopy(errors))
        fallback_errors = validate_document(fallback, schema, semantic_validator)
        manifest.append({"stage": "FALLBACK", "sha256": _hash(fallback),
                         "errors": fallback_errors})
        if not fallback_errors:
            return {"status": "VALID_FALLBACK", "document": fallback,
                    "manifest": manifest}
    return {"status": "UNRECOVERABLE", "document": None, "manifest": manifest}
