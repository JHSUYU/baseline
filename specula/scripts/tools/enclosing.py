import re, sys
root = sys.argv[1]
KW = ("if", "for", "while", "switch", "catch", "synchronized", "return", "throw", "new", "else", "try", "do")
for spec in sys.argv[2:]:
    path, line = spec.rsplit(":", 1)
    lines = open(f"{root}/{path}", errors="replace").read().splitlines()
    k = int(line) - 1
    while k >= 0:
        l = lines[k].strip()
        m = re.match(r"(?:(?:public|protected|private|static|final|synchronized|abstract)\s+)*(?:<[^>]+>\s+)?[\w.<>\[\], ?]+\s+(\w+)\s*\(", l)
        if m and m.group(1) not in KW and not l.startswith(KW) and not l.endswith(";") and "=" not in l.split("(")[0]:
            sig = l
            j = k
            while "{" not in sig and j + 1 < len(lines):
                j += 1; sig += " " + lines[j].strip()
            print(f"{spec.split('/')[-1]}: {k+1}: {sig.split('{')[0].strip()}")
            break
        k -= 1
