"""Diagnostic: roept de pipeline's EIGEN poll_into_buffers + flush aan.
Laat zien of de consumer records leest en de lake schrijft."""
import sys, time
sys.path.insert(0, "/app")
import pipeline.main as pm

p = pm.pipeline
print("BOOTSTRAP:", pm.KAFKA_BOOTSTRAP)
print("group id:", p._consumer is not None)

# lazy setup zoals run() dat doet
_ = p.lake
print("lake attached:", p.lake is not None and p._lake is not None)
_ = p.consumer
print("consumer ready:", p._consumer is not None)

for i in range(12):
    n = p.poll_into_buffers(max_wait_s=1.0)
    buf = {k: len(v) for k, v in p._buf.items() if v}
    if n or buf:
        print(f"[{i}] gepolld={n} buf={buf}")
    if buf:
        break
    time.sleep(0.5)

# flush wat er in de buffer zit
p.flush()
time.sleep(2)
try:
    c = p.lake.counts()
    print("AFTER FLUSH counts:", c)
except Exception as e:
    print("counts fout:", e)
