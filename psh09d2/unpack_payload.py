from pathlib import Path
import base64,gzip,json
root=Path(__file__).resolve().parent
text="".join(p.read_text(encoding="utf-8") for p in sorted(root.glob("payload.part*")))
payload=json.loads(text)
for name,data in payload.items():
    p=root/("input" if name=="d1_candidates.csv" else "")/name
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(gzip.decompress(base64.b64decode(data)))
    print(f"wrote {p} ({p.stat().st_size} bytes)")
