#!/usr/bin/env python3
"""prepare_known.py golden <case> | copy <case> [dir] -- the 14 known bugs, at their buggy versions.

golden: make known/<case>/golden/ once from the Specula known-bug case (its tree is the bug's buggy version,
  the parent of the fix, as a single commit `base` from `git archive`):
  - revert every change Specula's run made to the tree and drop its untracked files (keep the ported
    workload test, if the case has one);
  - remove .git and make a new one-commit history `base` (branch name kept);
  - copy the case's dependency cache; repoint Solr's lib/ links at it;
  - write env.sh (JDK 8, or JDK 7 + Ant 1.9.16 for solr-adhoc-k2; protoc 2.5.0 for HDFS).
  The golden tree is then built clean in a container (bin/build_known.sh).
copy: cases/<case>/agent/ (or [dir], for validation) from the built golden tree, plus the prompt.
"""
import glob, json, os, re, shutil, subprocess, sys

import yaml

R = "/bulk/codingagent"
S = "/bulk/specula-adhoc"
T = "/opt/tools"
TREES = ("hadoop", "hbase", "zookeeper", "lucene-solr")


def sh(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), check=True, capture_output=True, text=True).stdout


def spec_case(c):
    d = glob.glob(f"{S}/*/cases/{c}")[0]
    tree = next(t for t in TREES if os.path.isdir(f"{d}/{t}"))
    return d, tree


def env_sh(c, base):
    system = c.split("-")[0]
    deps = f"{base}/deps"
    if system in ("hdfs", "hbase"):
        e = [f"export JAVA_HOME={T}/jdk8", f"export MAVEN_HOME={T}/apache-maven-3.9.15",
             "export PATH=$MAVEN_HOME/bin:$JAVA_HOME/bin:$PATH",
             f'export MAVEN_OPTS="-Xmx8g -Dmaven.repo.local={deps}"   # local repository with every dependency; builds run offline (mvn -o)']
        if system == "hdfs":
            e[2:2] = [f"export PATH={T}/protoc-2.5.0/bin:$PATH", f"export LD_LIBRARY_PATH={T}/protoc-2.5.0/lib",
                      f"export HADOOP_PROTOC_PATH={T}/protoc-2.5.0/bin/protoc"]
    elif system == "zk":
        e = [f"export JAVA_HOME={T}/jdk8", f"export ANT_HOME={T}/apache-ant-1.10.14",
             "export PATH=$ANT_HOME/bin:$JAVA_HOME/bin:$PATH",
             f"export IVY_USER_DIR={deps}/ivy-home   # Ivy cache with every dependency",
             "# Ant picks ANT_ARGS up on every invocation; the repository URLs point nowhere, so builds stay offline.",
             f'export ANT_ARGS="-lib {deps}/ivy-lib -Divy.jar.exists=true -Divy.home=$IVY_USER_DIR '
             '-Divy.default.ivy.user.dir=$IVY_USER_DIR -Drepo.maven.org=http://127.0.0.1:9/ '
             '-Drepo.jboss.org=http://127.0.0.1:9/ -Divy.cache.ttl.default=eternal"',
             'export ANT_OPTS="-Xmx4g"']
    else:
        jdk, ant = ("jdk7", "apache-ant-1.9.16") if c == "solr-adhoc-k2" else ("jdk8", "apache-ant-1.10.14")
        e = [f"export JAVA_HOME={T}/{jdk}", f"export ANT_HOME={T}/{ant}", "export PATH=$ANT_HOME/bin:$JAVA_HOME/bin:$PATH",
             f"export IVY_USER_DIR={deps}   # Ivy cache with every dependency; pass ant -lib $IVY_USER_DIR/lib",
             'export ANT_OPTS="-Xmx4g -Divy.default.ivy.user.dir=$IVY_USER_DIR -Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 '
             '-Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9"   # offline: every dependency is in $IVY_USER_DIR']
    return "# Build environment: source this file before building or running tests.\n" + "\n".join(e) + "\n"


def repoint(tree_dir, new_deps):
    """Solr's lib/ links point into an Ivy cache (.../deps/<rest>): point them at new_deps/<rest>."""
    n = 0
    for root, dirs, files in os.walk(tree_dir):
        if ".git" in dirs:
            dirs.remove(".git")
        for f in files + dirs:
            p = os.path.join(root, f)
            if os.path.islink(p):
                t = os.readlink(p)
                if "/deps/" in t:
                    rest = t.split('/deps/', 1)[1]
                    nt = f"{new_deps}/{rest}"
                    if not os.path.exists(nt) and rest.startswith("ivy/") and os.path.exists(f"{new_deps}/{rest[4:]}"):
                        nt = f"{new_deps}/{rest[4:]}"   # a few links name an older layout of the same cache
                    if not os.path.exists(nt) and os.path.exists(t):
                        raise SystemExit(f"missing link target {nt}")
                    os.remove(p); os.symlink(nt, p); n += 1
    return n


def golden(c):
    sd, tree = spec_case(c)
    g = f"{R}/known/{c}/golden"
    if os.path.exists(f"{g}/{tree}"):
        print(f"{c}: golden exists"); return
    os.makedirs(g, exist_ok=True)
    part = f"{g}/{tree}.partial"
    if os.path.exists(part):
        sh(["rm", "-rf", part])
    sh(["cp", "-a", f"{sd}/{tree}", part])
    t = yaml.safe_load(open(f"{sd}/target.yaml"))
    wl_cls = t["workload"]["test"].split("#")[0].rsplit(".", 1)[-1]
    sh(["git", "checkout", "--", "."], cwd=part)
    untracked = sh(["git", "ls-files", "-o", "--exclude-standard"], cwd=part).split("\n")
    kept, dropped = [], []
    for u in filter(None, untracked):
        if u.endswith(f"/{wl_cls}.java"):
            kept.append(u)
        else:
            dropped.append(u); os.remove(f"{part}/{u}")
    branch = re.sub(r"^ref: refs/heads/", "", open(f"{part}/.git/HEAD").read().strip()) or "main"
    excl = open(f"{part}/.git/info/exclude").read() if os.path.exists(f"{part}/.git/info/exclude") else ""
    sh(["rm", "-rf", f"{part}/.git"])
    sh(["git", "init", "-q", "-b", branch], cwd=part)
    # Keep the source tree's local excludes (old ZooKeeper ignores build/ only there): else build output is committed.
    open(f"{part}/.git/info/exclude", "a").write(excl)
    sh("git -c user.name=base -c user.email=base@localhost add -A && "
       "git -c user.name=base -c user.email=base@localhost commit -q -m base", cwd=part)
    os.rename(part, f"{g}/{tree}")
    sh(["cp", "-a", f"{sd}/deps", f"{g}/deps"])
    links = repoint(f"{g}/{tree}", f"{g}/deps")
    open(f"{g}/env.sh", "w").write(env_sh(c, g))
    json.dump({"case": c, "from": f"{sd}/{tree}", "kept_untracked": kept, "dropped_untracked": dropped,
               "branch": branch, "solr_links_repointed": links}, open(f"{R}/known/{c}/golden.json", "w"), indent=1)
    print(f"{c}: golden made; kept {kept}; dropped {dropped}; {links} links")


def copy(c, dest=None, src="golden"):
    _, tree = spec_case(c)
    g = f"{R}/known/{c}/{src}"
    cdir = f"{R}/cases/{c}"
    agent = dest or f"{cdir}/agent"
    if os.path.exists(f"{agent}/{tree}"):
        print(f"{c}: already prepared"); return
    for d in (f"{agent}/home/.claude", f"{agent}/tmp", f"{cdir}/logs"):
        os.makedirs(d, exist_ok=True)
    os.chmod(f"{agent}/home/.claude", 0o700)
    sh(["cp", "-a", f"{g}/{tree}", f"{agent}/{tree}"])
    sh(["cp", "-a", f"{g}/deps", f"{agent}/deps"])
    repoint(f"{agent}/{tree}", f"{agent}/deps")
    open(f"{agent}/env.sh", "w").write(env_sh(c, agent))
    if dest is None:
        shutil.copy(f"{R}/known/targets/{c}.yaml", f"{cdir}/target.yaml")
        p = subprocess.run(["python3", "-I", f"{R}/bin/make_prompt.py", f"{cdir}/target.yaml", f"{agent}/{tree}",
                            f"{agent}/env.sh", f"{agent}/result.json"], check=True, capture_output=True, text=True).stdout
        open(f"{cdir}/prompt.md", "w").write(p)
    print(f"{c}: prepared {agent}/{tree}")


def fixed(c):
    """known/<case>/fixed: a copy of the built golden tree plus the fix's production changes (operator only)."""
    _, tree = spec_case(c)
    d = f"{R}/known/{c}/fixed"
    if os.path.exists(f"{d}/{tree}"):
        print(f"{c}: fixed exists"); return
    copy(c, d)
    diff = f"{R}/known/fixes/{c}.prod.diff"
    r = subprocess.run(["git", "apply", "--whitespace=nowarn", diff], cwd=f"{d}/{tree}", capture_output=True, text=True)
    if r.returncode != 0:
        r = subprocess.run(["patch", "-p1", "--fuzz=3", "-i", diff], cwd=f"{d}/{tree}", capture_output=True, text=True)
    print(f"{c}: fixed tree, patch rc={r.returncode} {r.stdout[-300:]} {r.stderr[-300:]}")
    if r.returncode != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    mode, c = sys.argv[1], sys.argv[2]
    if mode == "golden":
        golden(c)
    elif mode == "fixed":
        fixed(c)
    elif mode == "copyfixed":   # validation on the fixed version
        copy(c, sys.argv[3], src="fixed")
    else:
        copy(c, sys.argv[3] if len(sys.argv) > 3 else None)
