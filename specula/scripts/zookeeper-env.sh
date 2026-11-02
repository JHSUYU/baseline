# Environment for the Specula ad hoc runs on ZooKeeper (apache/zookeeper eab16599, release 8 bytecode).
export SPECULA_ADHOC_ROOT=/bulk/specula-adhoc
export JAVA_HOME=$SPECULA_ADHOC_ROOT/jdk/jdk-17.0.21+9
export JAVA21_HOME=$SPECULA_ADHOC_ROOT/jdk/jdk-21.0.13+9
export MAVEN_HOME=$SPECULA_ADHOC_ROOT/apache-maven-3.9.15
export PATH=$MAVEN_HOME/bin:$JAVA_HOME/bin:$PATH
export MAVEN_OPTS="-Xmx8g -Dmaven.repo.local=$SPECULA_ADHOC_ROOT/m2-zookeeper"
