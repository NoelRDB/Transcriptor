# Contribuir

Antes de proponer un cambio:

```powershell
npm ci
uv sync --project sidecar --extra dev --locked
npm run check
npm run release:verify
```

No añadas medios personales. Las pruebas deben generar sus propios archivos pequeños o usar material con una licencia compatible y documentada.

No registres texto transcrito, huellas de voz, rutas completas del usuario ni credenciales. No incorpores modelos o FFmpeg directamente al repositorio: utiliza los gestores y scripts de empaquetado existentes.

Describe en cada cambio:

- comportamiento antes y después;
- pruebas ejecutadas;
- impacto en privacidad y rendimiento;
- dependencia o licencia nueva, si existe.
