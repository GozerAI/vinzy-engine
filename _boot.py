import pathlib,json,sys
BASE=pathlib.Path(sys.argv[1])
for n,c in json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")).items():
 (BASE/n).write_text(c,encoding="utf-8")
 print(f"  {n}: {len(c)}b")
