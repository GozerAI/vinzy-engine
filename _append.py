import pathlib,sys,base64
p=pathlib.Path("F:/Projects/vinzy-engine/_gen_final.py")
data=sys.stdin.read().strip()
p.write_text(p.read_text(encoding="utf-8")+base64.b64decode(data).decode("utf-8"),encoding="utf-8")
print(f"appended {len(data)} b64 chars")
