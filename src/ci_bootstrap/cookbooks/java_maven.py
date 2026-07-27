"""Cookbook: Java built with Maven.

This is the template to copy when adding a new language: fill in the toolchain
setup, the build/test commands, the Sonar scanner invocation, and a default
Dockerfile, then `register(...)`. The 4-phase structure and the guards come from
base.py -- you never touch them here.
"""

from __future__ import annotations

from .base import Cookbook, register

# SonarCloud defaults; the reviewer overrides the org/projectKey if theirs differ.
# The Sonar step is skipped entirely until a SONAR_TOKEN secret is set (see base).
_SONAR_ARGS = (
    "-Dsonar.host.url=https://sonarcloud.io "
    "-Dsonar.organization=${{ github.repository_owner }} "
    "-Dsonar.projectKey=${{ github.repository_owner }}_${{ github.event.repository.name }}"
)

register(Cookbook(
    key="maven",
    language="java",
    display_name="Java (Maven)",
    setup=[
        {
            "name": "Set up JDK",
            "uses": "actions/setup-java@v4",
            # JDK 21: the SonarCloud scanner requires a modern runtime; Maven
            # still compiles to whatever release the pom targets.
            "with": {"distribution": "temurin", "java-version": "21", "cache": "maven"},
        },
    ],
    build=["mvn -B -DskipTests package"],
    test=["mvn -B verify"],
    sonar=[
        {
            "name": "Sonar scan",
            # Full plugin coordinates avoid the flaky `sonar:` prefix resolution
            # when the pom doesn't declare the scanner plugin itself.
            "run": f"mvn -B org.sonarsource.scanner.maven:sonar-maven-plugin:sonar {_SONAR_ARGS}",
        },
    ],
    default_dockerfile="""FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY . .
RUN mvn -B -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
""",
))
