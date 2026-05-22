# B2B Document Automation Engine - Enterprise Directory Topology

This document maps out our highly decoupled, clean-coded architecture. Every subdirectory is strictly a single, descriptive, and professional technical English word.

```text
├── schema/            # Database Layer & ORMs
│   ├── database.py    # Connections, Session makers, Naming Conventions
│   └── models.py      # Declarative SQL models (Tenants, Templates, Audits)
│
├── arabic/            # Arabic Reshaping & BiDi Engine Orchestration
│   └── engine.py      # Ligature shaping, alignment, and Amiri .ttf ingestion
│
├── engine/            # Percentage-to-PostScript Geometry Compilers
│   └── vector.py      # MediaBox, CropBox, and Rotation translation matrix
│
├── storage/           # Isolated Object Storage Adapters
│   └── adapter.py     # Base Protocol, Local storage, and Supabase integrations
│
├── api/               # Router endpoints & Ingestion Guards
│   └── v1.py          # FastAPI v1 endpoints, Logging, Security Controls
│
├── template/          # Configuration Templates
│   └── g12.json       # Production template schemas (Versioned structures)
│
├── web/               # Responsive SPA Frontend Assets and Store definitions
│   └── interactive.js # Alpine.js state stores, canvas monitors, map metrics
│
└── deploy/            # Provisioning templates and scripts
    └── render.yaml    # Render Infrastructure blueprint configuration
```

- **Clean Coding**: Decoupled service layers prevent business logic from leaking to delivery systems or external providers.
- **Single Responsibility**: Each module acts independently, linked together through clean programmatic contracts.
