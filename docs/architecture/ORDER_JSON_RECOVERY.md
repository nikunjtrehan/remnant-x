# Recover unreadable model orders without weakening requirement checks

An HTTP-successful model call can still contain no readable order JSON.
Previously, that response entered the model-success branch; an unreadable or
unavailable Fireworks repair could escape with `ERR_MODEL_ORDER_JSON` instead
of reaching the existing bounded fallback. The fallback also rejected a comma
before “each” in an otherwise supported millimetre request.

Unusable JSON now reaches the limited deterministic parser after at most one
configured repair attempt. The fallback accepts that punctuation and still
checks quantities, dimensions, thickness, kerf and exact material grade against
the original request. Semantically wrong model orders are not silently accepted;
failed repairs preserve the original requirement violation. Traces identify
local fallback and attempted repair rather than claiming a model parsed it.

Regression input:

> Cut 10 circles, each 50 mm in diameter, from 0.1 mm ss304 sheet. Kerf 0.2 mm.

Eight backend cases cover malformed replies, failed repairs, offline grammar,
successful repair, unchanged requirement guards and the HTTP parsing route.
The running API also returned the exact expected order using Baseten.
Parsing did not change inventory. Frontend guidance provides a clear retry or
**Build parts list** action, with diagnostic codes retained in support details.
