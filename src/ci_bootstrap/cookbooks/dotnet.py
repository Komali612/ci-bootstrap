"""Cookbook: .NET (dotnet CLI, C#).

Same shape as java_maven.py. The Sonar phase for .NET is a few steps -- the
scanner is a global tool wrapped around a build, and it needs a JDK to run --
so this cookbook contributes several named Sonar steps. base.py guards each of
them behind SONAR_TOKEN automatically.
"""

from __future__ import annotations

from .base import Cookbook, register

_SONAR_BEGIN = (
    'dotnet-sonarscanner begin '
    '/k:"${{ github.repository_owner }}_${{ github.event.repository.name }}" '
    '/o:"${{ github.repository_owner }}" '
    '/d:sonar.host.url="https://sonarcloud.io" '
    '/d:sonar.token="$SONAR_TOKEN"'
)

register(Cookbook(
    key="dotnet",
    language="csharp",
    display_name=".NET (C#)",
    setup=[
        {
            "name": "Set up .NET",
            "uses": "actions/setup-dotnet@v4",
            "with": {"dotnet-version": "8.0.x"},
        },
    ],
    build=[
        "dotnet restore",
        "dotnet build --configuration Release --no-restore",
    ],
    test=[
        "dotnet test --configuration Release --no-build --verbosity normal",
    ],
    sonar=[
        {
            "name": "Sonar: set up JDK",  # the .NET scanner runs on a JVM
            "uses": "actions/setup-java@v4",
            "with": {"distribution": "temurin", "java-version": "17"},
        },
        {"name": "Sonar: install scanner", "run": "dotnet tool install --global dotnet-sonarscanner"},
        {"name": "Sonar scan begin", "run": _SONAR_BEGIN},
        {"name": "Sonar build", "run": "dotnet build --configuration Release"},
        {"name": "Sonar scan end", "run": 'dotnet-sonarscanner end /d:sonar.token="$SONAR_TOKEN"'},
    ],
    default_dockerfile="""FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
EXPOSE 8080
# TODO: set to your published entrypoint dll, e.g. MyApp.dll
ENTRYPOINT ["dotnet", "app.dll"]
""",
))
