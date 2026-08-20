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

    input_document = deepcopy(document)
    errors = validate_document(document, schema, semantic_validator)
    manifest.append({"stage": "INPUT", "sha256": _hash(document), "errors": errors})
    if not errors:
        return {"status": "VALID_DETERMINISTIC" if unfenced else "VALID_ORIGINAL",
                "document": document, "manifest": manifest}

    changed = unfenced
    deterministic_refusals = []
    for path, mapping in (aliases or {}).items():
        if any(path == root or path.startswith(root + "/") for root in immutable_paths):
            deterministic_refusals.append({"code": "ALIAS_REFUSED_IMMUTABLE",
                                           "path": path})
            continue
        try: current = _get(document, path)
        except (KeyError, IndexError, TypeError, ValueError): continue
        if current in mapping:
            _set(document, path, mapping[current], must_exist=True); changed = True
    for path, value in (defaults or {}).items():
        if any(path == root or path.startswith(root + "/") for root in immutable_paths):
            deterministic_refusals.append({"code": "DEFAULT_REFUSED_IMMUTABLE",
                                           "path": path})
            continue
        try: _get(document, path)
        except (KeyError, IndexError, TypeError, ValueError):
            try: _set(document, path, value)
            except (KeyError, IndexError, TypeError, ValueError): continue
            changed = True
    if changed or deterministic_refusals:
        errors = validate_document(document, schema, semantic_validator)
        manifest.append({"stage": "DETERMINISTIC", "sha256": _hash(document),
                         "errors": errors, "refusals": deterministic_refusals})
        if not errors:
            return {"status": "VALID_DETERMINISTIC", "document": document,
                    "manifest": manifest}

    # A later refusal or newly revealed error can never widen the paths authorised by the
    # original validation. Otherwise merely naming a forbidden path would authorise it.
    authorised_paths = frozenset(error["path"] for error in errors)
    validation_errors = errors
    for attempt in range(max(0, max_model_attempts)):
        if provider is None: break
        allowed = sorted(authorised_paths)
        patches = provider.repair(deepcopy(document), deepcopy(validation_errors), allowed)
        candidate_document = deepcopy(document)
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
                _set(candidate_document, path, patch.get("value"),
                     must_exist=operation == "replace")
            except (KeyError, IndexError, TypeError, ValueError):
                rejected.append({"code": "PATCH_INVALID", "path": path,
                                 "message": "patch target does not match document"})
        if rejected:
            errors = rejected
            # Transactional batch: no accepted prefix survives one refused operation.
        else:
            document = candidate_document
            validation_errors = validate_document(document, schema, semantic_validator)
            errors = validation_errors
        manifest.append({"stage": "MODEL_REPAIR", "attempt": attempt + 1,
                         "sha256": _hash(document), "errors": errors})
        if not errors:
            return {"status": "VALID_MODEL_REPAIR", "document": document,
                    "manifest": manifest}

    if fallback_factory is not None:
        # Fallback begins from what entered the engine, never deterministic/model wreckage.
        fallback = fallback_factory(deepcopy(input_document), deepcopy(errors))
        fallback_errors = validate_document(fallback, schema, semantic_validator)
        manifest.append({"stage": "FALLBACK", "sha256": _hash(fallback),
                         "errors": fallback_errors})
        if not fallback_errors:
            return {"status": "VALID_FALLBACK", "document": fallback,
                    "manifest": manifest}
    return {"status": "UNRECOVERABLE", "document": None, "manifest": manifest}
