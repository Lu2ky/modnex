# Contribuir

Gracias por querer mejorar Modnex. Antes de empezar, lee [docs/arquitectura.md](docs/arquitectura.md): explica las capas y
dónde va cada cosa.

- **Ramas y commits.** `main` está protegida. Cada cambio va en su propia rama (`feat/…` o `fix/…`) y entra por un pull
  request; un cambio por rama y un commit por cambio, con un mensaje que diga qué cambia, por qué y cómo lo verificaste.
- **Pruebas.** Antes de abrir el pull request:
  ```bash
  python3 -I -m unittest discover -s tests      # unitarias, sin red
  python3 tests/e2e_core.py                     # API de extremo a extremo
  python3 tests/e2e_security.py                 # 2FA, política de administradores y túneles simulados
  python3 tests/e2e_ui.py                       # interfaz en un navegador real (pip install playwright)
  ```
  Si añades lógica, añade su prueba. Las pruebas de extremo a extremo usan puertos 8821–8824 y no tocan tu `config.json`.
- **Panel.** No admite estilos ni scripts en línea (política de seguridad de contenido): usa clases CSS y archivos.
  Respeta `prefers-reduced-motion` y `prefers-reduced-transparency`. Los iconos animados (avisos, confirmaciones,
  subidas, estados vacíos) salen de `static/motion.js` y sus animaciones viven en `static/style.css`; úsalos en vez de
  dibujar otros.
- **Capas.** Los servicios no importan de `web/`; lo que necesiten del exterior lo piden a `infra/` o lo reciben por
  parámetro. Una ruta nueva declara su permiso con `@route` o `@server_action`.
- **Secretos.** No incluyas `config.json`, claves de API ni tokens.

Tu contribución se publica bajo la misma licencia del proyecto (AGPL-3.0).
