# Environment for the Specula ad hoc runs on Solr (apache/lucene-solr faca81bff1, branch_8_11, Ant + Ivy, JDK 11).
export SPECULA_ADHOC_ROOT=/bulk/specula-adhoc
export JAVA_HOME=$SPECULA_ADHOC_ROOT/jdk/jdk-11
export JAVA21_HOME=$SPECULA_ADHOC_ROOT/jdk/jdk-21.0.13+9
export ANT_HOME=$SPECULA_ADHOC_ROOT/apache-ant-1.10.14
export PATH=$ANT_HOME/bin:$JAVA_HOME/bin:$PATH
export IVY_USER_DIR=$SPECULA_ADHOC_ROOT/ivy-solr   # Ivy cache with every dependency; pass -Divy_install_path / -Divy.default.ivy.user.dir if overridden
export ANT_OPTS="-Xmx4g -Divy.default.ivy.user.dir=$IVY_USER_DIR"
