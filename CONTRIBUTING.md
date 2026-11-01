# Contribuer

Décris le besoin dans une issue avant une évolution importante. Pour une correction,
indique un exemple minimal et ajoute un test de régression lorsque c’est possible.

```bash
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

Pour une modification du PDF, régénère la démonstration, rends ses pages avec
`pdftoppm -png` et vérifie l’absence de texte coupé ou superposé. Les tests PDF
vérifient aussi les signets, liens, caractères accentués et fins de lignes longues.
N’ajoute ni jetons, ni données privées dans les exemples.
