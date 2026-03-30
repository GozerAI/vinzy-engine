import pathlib, base64, sys
data = sys.stdin.read().strip()
content = base64.b64decode(data).decode("utf-8")
target = sys.argv[1]
pathlib.Path(target).write_text(content, encoding="utf-8")
print(f"wrote {target} ({len(content)} bytes)")
