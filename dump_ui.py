import uiautomator2 as u2, re, sys
sys.stdout.reconfigure(encoding="utf-8")
d = u2.connect("emulator-5554")
xml = d.dump_hierarchy()
texts = [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]
ids   = [i for i in re.findall(r'resource-id="([^"]+)"', xml) if i.strip()]
print("=== TEXTS ===")
for t in texts: print(f"  {t}")
print("=== RESOURCE IDs ===")
for i in ids: print(f"  {i}")
