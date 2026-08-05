#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# new-test-service.sh — create a ready-to-run .NET test service on GitHub.
#
# Makes a tiny ASP.NET (net8.0) web service that serves
#     GET /greeting?name=Bob   ->   {"message":"Hello, Bob!"}
# with a WORKING Dockerfile (so CI+CD actually deploys and runs it), pushes it
# to a NEW public repo under YOUR GitHub account, and prints the URL. Use it to
# get practice repos for the CI / CI+CD / CD agents without touching anyone
# else's repositories.
#
#   bash scripts/new-test-service.sh my-test-1 8080
#   bash scripts/new-test-service.sh my-test-2 8081     # different port -> run both at once
#
# Needs: the GitHub CLI (gh) signed in with `gh auth login`, and git.
# You do NOT need .NET installed locally — CI builds it in the cloud.
# Set DRY_RUN=1 to only generate the files locally (no GitHub repo created).
# ---------------------------------------------------------------------------
set -euo pipefail

if [ -t 1 ]; then G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; Z=$'\033[0m'; else G=""; Y=""; R=""; Z=""; fi
ok(){  printf "  %s✓%s %s\n" "$G" "$Z" "$1"; }
no(){  printf "  %s✗%s %s\n" "$R" "$Z" "$1" >&2; }
tip(){ printf "  %s!%s %s\n" "$Y" "$Z" "$1"; }

name="${1:-}"
port="${2:-}"
if [ -z "$name" ] || [ -z "$port" ]; then
  no "Usage: bash scripts/new-test-service.sh <repo-name> <port>"
  echo "     e.g. bash scripts/new-test-service.sh my-test-1 8080"
  exit 1
fi
if ! printf '%s' "$name" | grep -qE '^[A-Za-z0-9._-]+$'; then
  no "Repo name '$name' has invalid characters. Use letters, numbers, - _ . only."
  exit 1
fi
if ! printf '%s' "$port" | grep -qE '^[0-9]+$' || [ "$port" -lt 1024 ] || [ "$port" -gt 65535 ]; then
  no "Port '$port' must be a number between 1024 and 65535 (e.g. 8080)."
  exit 1
fi

# --- resolve gh (may be off this shell's PATH, e.g. conda base) -------------
GH=""
for cand in "$(command -v gh 2>/dev/null || true)" /opt/homebrew/bin/gh /usr/local/bin/gh /usr/bin/gh "$HOME/.local/bin/gh"; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then GH="$cand"; break; fi
done
if [ -z "${DRY_RUN:-}" ]; then
  if [ -z "$GH" ]; then
    no "GitHub CLI (gh) not found. Install from https://cli.github.com then run: gh auth login"
    exit 1
  fi
  if ! "$GH" auth status >/dev/null 2>&1; then
    no "You're not signed in to GitHub. Run:  $GH auth login   then try again."
    exit 1
  fi
  owner="$("$GH" api user --jq .login)"
else
  owner="YOU"
fi

# --- lay the project out in a temp folder ----------------------------------
work="$(mktemp -d)"
dir="$work/$name"
mkdir -p "$dir/src/DotnetService" "$dir/tests/DotnetService.Tests"

# Dockerfile — the ONE file that varies by port (unquoted heredoc so $port fills in)
cat > "$dir/Dockerfile" <<EOF
# Builds and runs the ASP.NET service. The published DLL is DotnetService.dll
# (from src/DotnetService/DotnetService.csproj); it listens on port $port.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish src/DotnetService/DotnetService.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_HTTP_PORTS=$port
EXPOSE $port
ENTRYPOINT ["dotnet", "DotnetService.dll"]
EOF

# Everything below is fixed content — QUOTED heredocs so nothing is expanded
# (the C# uses $"..." interpolation which must stay literal).
cat > "$dir/.gitignore" <<'EOF'
bin/
obj/
TestResults/
.ci-agent-logs/
classification.json
.idea/
.vs/
.DS_Store
EOF

cat > "$dir/DotnetService.sln" <<'EOF'
Microsoft Visual Studio Solution File, Format Version 12.00
# Visual Studio Version 17
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "DotnetService", "src\DotnetService\DotnetService.csproj", "{9A1B2C3D-0001-4000-8000-000000000001}"
EndProject
Project("{FAE04EC0-301F-11D3-BF4B-00C04F79EFBC}") = "DotnetService.Tests", "tests\DotnetService.Tests\DotnetService.Tests.csproj", "{9A1B2C3D-0002-4000-8000-000000000002}"
EndProject
Global
	GlobalSection(SolutionConfigurationPlatforms) = preSolution
		Debug|Any CPU = Debug|Any CPU
		Release|Any CPU = Release|Any CPU
	EndGlobalSection
	GlobalSection(ProjectConfigurationPlatforms) = postSolution
		{9A1B2C3D-0001-4000-8000-000000000001}.Debug|Any CPU.ActiveCfg = Debug|Any CPU
		{9A1B2C3D-0001-4000-8000-000000000001}.Debug|Any CPU.Build.0 = Debug|Any CPU
		{9A1B2C3D-0001-4000-8000-000000000001}.Release|Any CPU.ActiveCfg = Release|Any CPU
		{9A1B2C3D-0001-4000-8000-000000000001}.Release|Any CPU.Build.0 = Release|Any CPU
		{9A1B2C3D-0002-4000-8000-000000000002}.Debug|Any CPU.ActiveCfg = Debug|Any CPU
		{9A1B2C3D-0002-4000-8000-000000000002}.Debug|Any CPU.Build.0 = Debug|Any CPU
		{9A1B2C3D-0002-4000-8000-000000000002}.Release|Any CPU.ActiveCfg = Release|Any CPU
		{9A1B2C3D-0002-4000-8000-000000000002}.Release|Any CPU.Build.0 = Release|Any CPU
	EndGlobalSection
EndGlobal
EOF

cat > "$dir/src/DotnetService/DotnetService.csproj" <<'EOF'
<Project Sdk="Microsoft.NET.Sdk.Web">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>

</Project>
EOF

cat > "$dir/src/DotnetService/GreetingService.cs" <<'EOF'
namespace DotnetService;

public class GreetingService
{
    public const string DefaultName = "world";

    public string Greet(string? name)
    {
        var target = string.IsNullOrWhiteSpace(name) ? DefaultName : name.Trim();
        return $"Hello, {target}!";
    }
}
EOF

cat > "$dir/src/DotnetService/Program.cs" <<'EOF'
using DotnetService;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddSingleton<GreetingService>();

var app = builder.Build();

app.MapGet("/greeting", (string? name, GreetingService greetings) =>
    Results.Ok(new GreetingResponse(greetings.Greet(name))));

app.Run();

public record GreetingResponse(string Message);

// Exposes the implicit Program class to WebApplicationFactory in the test project.
public partial class Program
{
}
EOF

cat > "$dir/tests/DotnetService.Tests/DotnetService.Tests.csproj" <<'EOF'
<Project Sdk="Microsoft.NET.Sdk">

  <PropertyGroup>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <IsPackable>false</IsPackable>
  </PropertyGroup>

  <ItemGroup>
    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />
    <PackageReference Include="xunit" Version="2.9.2" />
    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />
    <PackageReference Include="coverlet.collector" Version="6.0.2" />
    <PackageReference Include="Microsoft.AspNetCore.Mvc.Testing" Version="8.0.8" />
  </ItemGroup>

  <ItemGroup>
    <ProjectReference Include="..\..\src\DotnetService\DotnetService.csproj" />
  </ItemGroup>

</Project>
EOF

cat > "$dir/tests/DotnetService.Tests/GreetingEndpointTests.cs" <<'EOF'
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Xunit;

namespace DotnetService.Tests;

public class GreetingEndpointTests : IClassFixture<WebApplicationFactory<Program>>
{
    private readonly HttpClient _client;

    public GreetingEndpointTests(WebApplicationFactory<Program> factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task GreetingEndpointReturnsMessage()
    {
        var response = await _client.GetFromJsonAsync<GreetingResponse>("/greeting?name=Komali");
        Assert.NotNull(response);
        Assert.Equal("Hello, Komali!", response!.Message);
    }

    [Fact]
    public async Task GreetingEndpointDefaults()
    {
        var response = await _client.GetFromJsonAsync<GreetingResponse>("/greeting");
        Assert.NotNull(response);
        Assert.Equal("Hello, world!", response!.Message);
    }
}
EOF

cat > "$dir/tests/DotnetService.Tests/GreetingServiceTests.cs" <<'EOF'
using Xunit;

namespace DotnetService.Tests;

public class GreetingServiceTests
{
    private readonly GreetingService _service = new();

    [Fact]
    public void GreetsByName()
    {
        Assert.Equal("Hello, Komali!", _service.Greet("Komali"));
    }

    [Fact]
    public void DefaultsWhenNameMissing()
    {
        Assert.Equal("Hello, world!", _service.Greet(null));
        Assert.Equal("Hello, world!", _service.Greet("   "));
    }

    [Fact]
    public void TrimsWhitespace()
    {
        Assert.Equal("Hello, Ada!", _service.Greet("  Ada "));
    }
}
EOF

cat > "$dir/README.md" <<EOF
# $name

A tiny ASP.NET (net8.0) test service for the cicd-bootstrap CI / CI+CD / CD agents.

\`\`\`
GET /greeting?name=<name>   ->   {"message": "Hello, <name>!"}
\`\`\`

It has **no CI/CD workflows** on purpose — point the agents at it to generate them.
The included Dockerfile runs \`DotnetService.dll\` and listens on **port $port**, so a
CD deploy serves a real response at http://localhost:$port/greeting?name=Bob
EOF

ok "generated the .NET service (listens on port $port)"

if [ -n "${DRY_RUN:-}" ]; then
  echo
  tip "DRY_RUN set — not creating a GitHub repo. Files are here:"
  echo "     $dir"
  ( cd "$dir" && find . -type f | sed 's/^/       /' | sort )
  exit 0
fi

# --- commit and create the repo on GitHub ----------------------------------
git -C "$dir" init -q
git -C "$dir" add -A
git -C "$dir" \
  -c user.name="cicd-bootstrap" -c user.email="cicd-bootstrap@users.noreply.github.com" \
  commit -q -m "initial .NET test service (port $port)"
git -C "$dir" branch -M main

echo "Creating https://github.com/$owner/$name and pushing…"
"$GH" repo create "$name" --public --source="$dir" --remote=origin --push \
  --description "cicd-bootstrap .NET test service (port $port)" >/dev/null
ok "repo created and pushed"

echo
echo "Ready: ${G}https://github.com/$owner/$name${Z}  (port $port)"
echo "Next:"
echo "  • CI only or CI+CD:  open http://127.0.0.1:8001/ and paste that URL"
echo "  • To DEPLOY it first attach a runner:"
echo "      bash scripts/add-runner.sh https://github.com/$owner/$name"
echo "  • After deploy, check:  http://localhost:$port/greeting?name=Bob"
