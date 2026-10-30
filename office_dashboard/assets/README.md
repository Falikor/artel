# Office scene assets

The PNG images and JSON manifests in this directory are included with Artel so a
fresh clone can display the office scene without downloading a separate pack.
They provide the office background and furniture, seven animated characters,
social and lounge animations, doors, and the optional cat.

Keep the directory structure intact: the dashboard discovers animation sets and
loads files referenced by their manifests. Companion metadata is included with
the pack, even when the renderer uses the combined manifest instead.

These files are published with the rights holder's authorization.

To use a different pack, set `OFFICE_ASSETS` or pass `--assets` when starting the
dashboard. See the [dashboard documentation](../README.md).

## Русский

PNG и JSON включены в репозиторий: офис, персонажи, двери, мебель и кошка доступны
сразу после клонирования. Сохраняйте структуру каталогов и связанные манифесты.
Публикация разрешена правообладателем.
