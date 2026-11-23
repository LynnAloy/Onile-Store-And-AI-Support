"""Run the Java payment suite on a disposable real MySQL clone, with a schema-only DB login."""
import json
import os
import re
import secrets
import shutil
import subprocess

os.environ["DEEPSEEKDOC_DEMO"] = "1"
from demo import guard, normal_config
from local_stack import RUN, JAVA, database, query, protect


def main():
    source = guard()
    suffix = secrets.token_hex(5)
    name = "DeepseekDoc_M51_Test_" + suffix
    username = "m51test_" + suffix
    password = secrets.token_urlsafe(32)
    config_file = RUN / "mysql-test-config.json"
    created, user_created = False, False
    with database(normal_config()) as admin:
        try:
            if query(admin, "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (name,)):
                raise RuntimeError("Scratch schema collision")
            with database(source) as demo:
                tables = [row[0] for row in query(demo, "SHOW TABLES")]
                if not all(re.fullmatch(r"[a-zA-Z0-9_]+", table) for table in tables):
                    raise RuntimeError("Unexpected table identifier")
                ddl = [query(demo, "SHOW CREATE TABLE `" + table + "`")[0][1] for table in tables]
            query(admin, "CREATE DATABASE `" + name + "` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
            created = True
            admin.select_db(name)
            query(admin, "SET FOREIGN_KEY_CHECKS=0")
            for sql in ddl:
                query(admin, sql)
            query(admin, "SET FOREIGN_KEY_CHECKS=1")
            query(admin, "CREATE TABLE m51_test_environment(marker VARCHAR(64) PRIMARY KEY)")
            query(admin, "INSERT INTO m51_test_environment VALUES ('m51-isolated-mysql-v1')")
            query(admin, "CREATE USER %s@'localhost' IDENTIFIED BY %s", (username, password))
            user_created = True
            query(admin, "GRANT ALL PRIVILEGES ON `" + name + "`.* TO %s@'localhost'", (username,))
            # Match the stack's preflight connection: authenticate the fresh caching_sha2 user,
            # and prove that this login cannot select the normal business database.
            import pymysql
            with database({**source, "DB_NAME": name, "DB_USERNAME": username, "DB_PASSWORD": password}) as probe:
                query(probe, "SELECT marker FROM m51_test_environment")
                try:
                    probe.select_db(normal_config().get("DB_NAME", "DeepSeekDoc"))
                except pymysql.err.OperationalError as exc:
                    if exc.args[0] != 1044:
                        raise
                else:
                    raise RuntimeError("Test database login can access the normal schema; refusing tests")
            config = {"database": name, "username": username, "password": password,
                "url": "jdbc:mysql://" + source.get("DB_HOST", "127.0.0.1") + ":" + source.get("DB_PORT", "3306")
                + "/" + name + "?useSSL=false&useUnicode=true&characterEncoding=utf-8&serverTimezone=GMT%2B8"}
            config_file.write_text(json.dumps(config), encoding="utf-8")
            protect(config_file)
            environment = os.environ.copy()
            environment.update({"M51_MYSQL_TEST": "true", "M51_MYSQL_CONFIG": str(config_file)})
            command = shutil.which("mvn.cmd") or shutil.which("mvn")
            if not command:
                raise RuntimeError("Maven not found")
            with (RUN / "logs/m6-real-mysql-java.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([command, "-Dtest=CommerceMySqlTests", "test"], cwd=JAVA,
                    env=environment, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            import xml.etree.ElementTree as ET
            suite = ET.parse(JAVA / "target/surefire-reports/TEST-com.example.mybatisplus.CommerceMySqlTests.xml").getroot()
            report = {"passed": result.returncode == 0 and suite.attrib["errors"] == "0" and suite.attrib["failures"] == "0",
                      "tests": int(suite.attrib["tests"]), "realMySQL": True,
                      "disposableSchemaOnly": True, "normalFundsChanged": False}
            (RUN / "m6-mysql-tests.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report))
            return 0 if report["passed"] else 1
        finally:
            config_file.unlink(missing_ok=True)
            if created:
                if not re.fullmatch(r"DeepseekDoc_M51_Test_[0-9a-f]{10}", name):
                    raise RuntimeError("Unsafe scratch cleanup")
                query(admin, "DROP DATABASE `" + name + "`")
            if user_created:
                query(admin, "DROP USER %s@'localhost'", (username,))


if __name__ == "__main__":
    raise SystemExit(main())
