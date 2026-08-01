# Materials structure discovery

ARIS treats remote materials databases and AiiDA as peer application capabilities.
The Materials app owns remote discovery and normalization. The AiiDA app owns the
managed worker and the creation of `StructureData` nodes.

## Boundary

```text
ARIS research agent
  -> materials capability
       -> Materials Project OPTIMADE
       -> Materials Cloud OPTIMADE
  -> normalized StructureArtifact
  -> AiiDA capability
       -> managed stdio JSON-RPC method structure.import
  -> StructureData PK
  -> submission preview
```

The worker never calls a remote materials API and does not expose an HTTP server.
ARIS owns outbound HTTP, provider selection, partial-failure handling, caching, and
the transition from a selected remote structure to an AiiDA import request.

## Explicit protocols

`StructureSearchRequest` carries provider, database, entry ID, formula, element,
stability, and result-limit fields. Search topology is never inferred from domain
phrases such as EOS.

`StructureArtifact` contains:

- lattice vectors and periodic boundary conditions;
- Cartesian sites and ordered or partially occupied species;
- provider, database, entry ID, immutable ID, retrieval time, source URL, license,
  citations, and provider fields.

`StructureResolution` records the agent-visible acquisition state using one of:

- `existing`
- `search_required`
- `selection_required`
- `selected`
- `imported`
- `unavailable`

The worker stores `aris_source_key` and `aris_structure_source` extras. The source
key uses the provider, database, entry ID, and immutable/version identifier so
repeated imports are idempotent by default.

## Interfaces

HTTP routes are mounted below `/api/materials`:

- `GET /providers`
- `POST /search`
- `POST /structure`
- `POST /import`

The standalone `aris-materials-mcp` entry point exposes provider listing,
structured search, and import preparation. The same MCP facade can additionally
expose idempotent import when ARIS composes it with the managed AiiDA capability;
the standalone MCP process never starts or owns aiida-worker.

The main research agent exposes equivalent tools and follows this sequence:

1. inspect compatible local AiiDA structures;
2. search remote providers only when needed;
3. ask the user when materially different polymorphs remain;
4. import one selected structure;
5. use the returned PK to prepare a calculation preview;
6. require the existing explicit confirmation before calculation submission.

## Built-in providers

Materials Project is available through its official OPTIMADE endpoint as database
`mp`. Materials Cloud exposes its current curated databases, with `mc3d-pbe-v1` as
the default search database; MC3D PBEsol, MC2D, topology, MOF, COF, interface, and
other listed databases can be selected explicitly.
