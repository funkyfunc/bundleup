# **Architectural Strategy for Self-Contained Python Programs: Workload Constraints, Artifact Taxonomies, and Bundler Mechanics**

## **Executive Summary: Strategic Landscape and High-Yield Opportunities**

Distributing software written in Python has historically required a compromise between brittle environment configuration on target machines and heavy operating system virtualization. While containerization has become the standard enterprise fallback, it introduces substantial disk bloat, daemon dependencies, slow cold starts, and complex build pipelines. A self-contained executable Python archive occupies a distinct and valuable design space: it provides an isolated, immutable application runtime on any host that already has a base Python interpreter, without requiring administrative privileges, package installers, compiler toolchains, or network access1.  
The workloads that derive the highest operational leverage from standalone Python bundling fall into four primary categories:

> 1. Serverless execution environments, specifically AWS Lambda, Azure Functions Flex Consumption, and Google Cloud Run functions, where deploying pre-packaged runtime archives avoids the multi-hundred-megabyte container images and slow cold starts associated with container runtimes4.  
> 2. Air-gapped and incident-response environments, where target systems are physically or logically disconnected from package repositories, and security protocols prohibit leaving untracked build artifacts across the host filesystem1.  
> 3. Distributed data frameworks such as Apache Spark and Ray, alongside High-Performance Computing (HPC) clusters, where dependency trees must be distributed across hundreds or thousands of nodes without triggering parallel package installations that saturate shared network filesystems like Lustre8.  
> 4. Host-embedded runtime environments and developer automation, including continuous integration pipelines, git hooks, and plugin ecosystems for software such as Blender, Splunk, and QGIS, where isolated execution must proceed without human intervention or environment management1.

Conversely, workloads requiring complete isolation from host dependencies—such as consumer desktop software for non-technical users who lack a pre-installed Python interpreter, or WebAssembly isolates running within V8 edge runtimes like Cloudflare Workers—are poorly served by standalone .pyz archives and require dedicated standalone binary compilers or Emscripten toolchains2.  
To maximize utility without succumbing to feature sprawl, an effective bundler should adopt a tiered output architecture centered around three core formats:

* A standardized .pyz zip application with an integrated extraction cache for native compiled extensions15.  
* A flat, uncompressed deployment archive (.zip) structured specifically for serverless runtimes and distributed job submission4.  
* A vendored directory format (dir) tailored for host application plugins and container layer assembly3.

Standalone platform executables embedding static interpreters, such as python-build-standalone paired with scie-jump or PyApp, should be integrated through composable downstream pipelines rather than bundled directly into the core packaging engine1.

## **Input Shapes: Mechanics, Failure Modes, and Tool Strategies**

Managing dependency inputs requires analyzing how various packaging structures interact with the Python import system, operating system loaders, and dynamic linkers.

### **Shape A: Single Script Using Only the Standard Library**

Single-file scripts relying exclusively on the standard library are ubiquitous in system administration, operational automation, and orchestration pipelines. Although conceptually simple, bundling these scripts introduces failure modes linked to interpreter evolution and filesystem assumptions.  
Python standard library interfaces evolve across minor versions, resulting in deprecations and removals, such as the elimination of distutils in Python 3.12 or variations in the asyncio and pathlib APIs. When a script is packaged into an archive, runtime failures often stem from code that inspects \_\_file\_\_ or sys.argv\[0\] to resolve adjacent templates, configuration files, or data directories. When encapsulated within a zip archive, these paths resolve to virtual paths rather than concrete filesystem locations, causing direct calls to built-in open() to raise FileNotFoundError.  
Existing tools handle this shape cleanly. The Python standard library zipapp module can package a script directory into an executable archive by prepending a POSIX shebang line1. The interpreter's internal zipimport mechanism mounts the archive directly onto sys.path, transparently loading pure Python modules into memory17.

### **Shape B: Code Plus Pure-Python Dependencies**

Applications composed of Python source code and third-party pure-Python packages (wheels with the py3-none-any tag) represent the baseline for internal utilities, API integrations, and automation tasks.  
The primary failure mode for pure-Python dependencies is zip-safety. Extensive legacy and modern Python packages assume an unpacked filesystem structure. Packages frequently inspect their own package roots to locate non-code assets such as SQL migration files, HTML templates, CSS bundles, or TLS certificates16. When imported from an unextracted zip archive, standard file I/O operations fail unless the code has been explicitly updated to use the importlib.resources or pkgutil APIs17. Furthermore, packages utilizing dynamic namespace declarations (such as legacy pkg\_resources style namespaces) can fail under zipimport if disparate zip entries attempt to contribute to the same logical namespace package without proper metadata configuration.  
Standard tools navigate this shape using different extraction strategies. The zipapp module can bundle dependencies unpacked into the archive root, but offers no fallback when dependencies prove non-zip-safe1. PEX constructs an executable zip application containing embedded wheels, intercepting the import system to extract non-zip-safe distributions into a local cache directory (\~/.pex/) upon execution22. Shiv adopts an all-or-nothing approach by packaging an entire virtual environment into a zip archive and extracting the entire payload into a version-hashed directory (\~/.shiv/) on initial launch, circumventing zip-safety issues at the expense of disk space and initial startup time16.

### **Shape C: Code Plus Compiled Python Dependencies**

Modern enterprise Python environments rely heavily on compiled C, C++, Cython, and Rust extensions, including performance-critical libraries such as cryptography, pydantic-core, numpy, and orjson.  
The fundamental technical barrier with compiled extensions is an operating system primitive: native dynamic linkers (dlopen on POSIX systems, LoadLibrary on Windows) operate exclusively on concrete filesystem paths or real kernel file descriptors mapped to virtual memory17. Dynamic linkers cannot resolve shared objects (.so, .dylib, or .pyd files) residing within compressed ZIP archives17. Consequently, the CPython zipimport engine raises an immediate ImportError when an import statement targets a compiled shared library within an archive17.  
Additional failure modes include:

* Application Binary Interface (ABI) incompatibilities, where extensions compiled for a specific Python minor release fail on others unless compiled strictly against the stable abi3 C-API;  
* C runtime library divergence, such as deploying wheels compiled against newer glibc versions onto older enterprise Linux systems or musl-based distributions like Alpine;  
* Inter-library dependency resolution, where an extension depends on adjacent bundled shared libraries via relative runpaths (RPATH/RUNPATH) that break if native files are extracted in isolation without their accompanying shared objects.

To execute compiled dependencies, PyInstaller bundles native shared objects into an executable archive and uncompresses them into an ephemeral directory in /tmp during every launch cycle, adding substantial startup latency2. PEX extracts compiled wheels into \$PEX\_ROOT/installed\_wheels/ and mutates sys.path to point directly to these disk-backed directories22. Shiv extracts the complete bundled virtual environment to disk16. PyOxidizer historically implemented custom in-memory ELF and PE loaders to link extensions directly from system memory, but encountered compatibility hurdles with complex third-party extensions that trigger secondary dynamic loading or POSIX signal handlers, ultimately requiring fallback disk extraction24.

### **Shape D: Code Plus Non-Python Dependencies**

Data science, machine learning, and automation workflows frequently incorporate external system artifacts, including system shared libraries (libpq.so, libGL.so), external standalone executables (FFmpeg, headless Chromium for Playwright), foreign runtimes (Node.js), large machine learning weight files, and GPU runtime libraries (CUDA, cuDNN).  
These assets fall outside the Python wheel packaging ecosystem. System libraries compiled without relative runpaths cannot locate their dependencies when extracted to non-standard paths. Standalone executables extracted into temporary directories fail to execute on security-hardened Linux systems where temporary partitions (/tmp, /var/tmp) are mounted with the noexec option17. Large data files and neural network weights introduce severe bundle size bloat, frequently breaching the memory, temporary disk, or payload limits of serverless and edge hosting platforms18. GPU libraries require tight compatibility with host-level kernel drivers, meaning bundled CUDA runtime libraries will fail if the target host runs an incompatible driver version.  
Existing tools generally treat external non-Python dependencies as beyond the scope of Python-specific packaging. Developers typically manage this shape using multi-stage container builds, system configuration tools, or conda and pixi environments that package both native system binaries and Python libraries into an integrated runtime4.

### **Shape E: Projects with Several Entry Points**

Enterprise applications commonly share a unified codebase across multiple operational entry points, such as a primary package providing an HTTP API, background asynchronous workers, batch database migrations, and administrative command-line tools.  
The .pyz specification permits only a single execution root: \_\_main\_\_.py. Standard zipapps lack native mechanisms to dynamically alter execution pathways based on external command-line flags or execution context without custom internal routing logic. Furthermore, production web servers such as Gunicorn and Uvicorn expect importable module path specifications (e.g., application.web:api) rather than script execution paths, complicating execution from encapsulated archives.  
PEX handles this requirement by exposing environment variable overrides, allowing operators to alter execution behavior at runtime using PEX\_MODULE=application.cli:main or PEX\_SCRIPT=worker20. When deploying standard zipapps, teams typically implement internal entry point routers inside \_\_main\_\_.py that parse the first positional argument to dispatch execution to specific internal functions.

## **Output Formats and Artifact Topologies**

The table below provides a comparative analysis of primary output formats across target prerequisites, operational characteristics, and security profiles.

| Output Format | Target Prerequisites | Offline Capable | Compiled Extensions Handling | Non-Python Assets & Binaries | Startup Latency & Footprint | Security & Signing Characteristics | Reference Tooling |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| **PEP 723 Inline Script** | Host Python plus uv or pipx \[cite: 1, 28\] | No; requires network access on initial execution28 | Downloaded or built dynamically during first run28 | Limited strictly to capabilities of standard wheels | High initial run latency; minimal source file footprint29 | Plaintext Python source; supports detached cryptographic signatures | uv run, pipx run \[cite: 1, 28, 30\] |
| **.pyz Zip Application** | Host Python interpreter only1 | Yes; fully self-contained | Incompatible with vanilla zipimport; requires extraction of native objects to disk17 | Static assets accessible via zipfile; executables require disk extraction16 | Near-zero startup latency for pure Python; bounded extraction penalty for native wheels16 | Central zip directory can be signed; susceptible to path traversal if decompression logic is unvalidated | Standard library zipapp, Shiv, bundleup1 |
| **PEX Archive** | Host Python interpreter only20 | Yes; when built with bundled wheel cache20 | Extracted into local cache directory (\$PEX\_ROOT) via import hooks or virtualenv generation22 | Arbitrary assets supported; executable binaries require extraction22 | Low to moderate latency; virtualenv mode amortizes startup overhead across invocations20 | Integrates cryptographic wheel hash verification; supports detached signatures22 | PEX, Pants20 |
| **Platform Zip (Serverless)** | Managed cloud runtime (AWS, Azure, GCP)4 | Yes; deployed directly to cloud storage | Pre-compiled against target environment architecture and laid out flat on sys.path \[cite: 4\] | Native shared libraries supported via system library paths (e.g., /opt/lib) | Low cold-start latency; requires zero on-instance archive extraction4 | Managed via cloud provider IAM, KMS encryption, and platform code signing | AWS SAM, Serverless Framework, uv export4 |
| **Containerless OCI Image** | Container runtime daemon (Docker, containerd)3 | Yes; once pulled to host registry | Pre-compiled and placed directly into base container filesystem layers3 | Native system packages, dynamic libraries, and arbitrary executables fully supported32 | High storage footprint (50–500MB); container runtime initialization adds overhead33 | OCI standard image signing (Cosign, Notary); immutable content-addressable digests3 | ko, jib, pycontainer-build \[cite: 3, 34\] |
| **Standalone Native Executable** | Nothing; runs directly on operating system20 | Yes; fully self-contained | Fully supported; embeds interpreter, extensions, and runtime dependencies together2 | Supported via archive extraction or embedded virtual filesystems2 | High disk size (30–120MB); startup requires uncompressing binary or launching bundled interpreter2 | Subject to OS binary signing and notarization (Apple Gatekeeper, Windows Authenticode) | PyInstaller, Nuitka, PyApp, scie-jump \[cite: 2, 20, 35\] |
| **Vendored Directory** | Host application embedding Python11 | Yes; distributed with host application | Must match host embedded interpreter ABI and runtime library versions precisely11 | Highly restricted; constrained by host process address space and security sandbox | Zero startup penalty; libraries reside uncompressed directly on host filesystem18 | Validated through host application plugin verification systems36 | pip install \--target, pip-vendor |
| **Wheelhouse Archive** | Host Python runtime plus package installer (pip, uv)1 | Yes; operates as local package repository | Pre-compiled wheels matched to target architectures; installed at target site | Restricted to standard wheel file formats | High installation latency; must be built into virtualenv before execution | Standard wheel metadata signatures and cryptographic checksums | pip wheel, uv cache |
| **Conda / Pixi Pack** | Host OS with compatible C runtime (glibc)10 | Yes; packaged tarball | Fully supported; handles arbitrary C, C++, Fortran, and Rust libraries natively27 | Fully supported; packages arbitrary non-Python binaries, CUDA, and compilers37 | Very large archive sizes (100MB–2GB); requires archive extraction prior to activation10 | Checksum verification of package manifests; non-standard signature models | conda-pack, pixi-pack \[cite: 10, 27\] |
| **Data Platform Zip** | Distributed cluster runtime (PySpark, Ray)8 | Yes; distributed from driver node | Pure Python supported natively; compiled extensions require worker-level extraction hooks39 | Limited; assets distributed across worker scratch directories40 | Amortized across task scheduling; memory overhead if broadcasted inefficiently42 | Controlled via cluster security boundary and shared object store ACLs8 | spark-submit \--py-files, Ray runtime\_env \[cite: 8, 43, 44\] |
| **WebAssembly Archive** | Web browser or Wasm edge runtime (Cloudflare Workers)13 | Yes; bundled with worker asset | Extensions must be compiled to Emscripten/Wasm targets; native ELF .so fails14 | Strictly sandboxed; cannot invoke arbitrary system binaries or raw sockets | Highly optimized startup via V8 memory snapshots; strict memory ceilings (128MB)7 | Encapsulated within Wasm capability-based security model14 | Pyodide, wrangler \[cite: 13, 14\] |

## **Dual-Mode Artifact Viability**

The proposition of creating a single hybrid artifact that satisfies multiple execution paradigms—such as a .pyz archive that also carries PEP 723 inline dependency metadata—introduces technical trade-offs between portability and operational stability.

### **The Mechanics of Hybrid Archives**

A zip archive is physically read from the end of the file by locating the End of Central Directory (EOCD) record and traversing backward to parse the Central Directory headers. Because the zip specification does not require archive data to start at byte offset zero, POSIX systems have long supported prepending an arbitrary header (such as a shell shebang line) to the front of a zip archive without corrupting the archive's internal structures15.  
PEP 723 defines inline script metadata enclosed within structured comment blocks positioned at the top of a script file. Because Python interpreters treat lines beginning with \# as comments, it is syntactically valid to prepend an extended header containing both an executable shebang line and a PEP 723 metadata block directly to a .pyz archive payload15. When invoked directly via python application.pyz, the CPython zipapp loader skips the leading text header and executes \_\_main\_\_.py from the archive root1.

### **Execution Divergence and Failure Modes**

While physically constructible, dual-mode artifacts introduce significant operational friction:

> 1. **Parser Execution Failures:** High-speed package managers like uv expect PEP 723 scripts to be UTF-8 encoded text files15. When uv run inspects a file to locate metadata, trailing binary zip bytes can trigger decoding errors or cause the tool to reject the file as binary data unless specific file-scanning boundaries are enforced upstream (as tracked in astral-sh/uv\#18662)15.  
> 2. **Execution Divergence and Environment Drift:** If an operator executes python application.pyz, the application runs against the host interpreter using the bundled, locked dependencies frozen inside the zip archive. If the operator instead invokes uv run application.pyz, uv parses the inline metadata header, provisions an isolated virtual environment on the host machine, downloads packages matching the loose PEP 723 version bounds from PyPI, and executes the application in that environment15. The two invocations execute against completely different dependency trees. The embedded, bit-for-bit locked wheel distributions inside the archive are completely ignored by uv run, defeating the purpose of hermetic bundling.  
> 3. **Fallback Scripts:** Providing a shell bootstrap script that checks for the presence of uv, installs missing dependencies when connected to a network, and falls back to an embedded wheel cache when offline introduces extreme fragility. Shell script abstraction layers fail across cross-platform boundaries (e.g., POSIX shell vs. Windows cmd.exe/PowerShell) and introduce indeterminism into automated environments where reproducible execution is mandatory.

A self-contained deployment artifact must maintain an unambiguous execution contract: it should run hermetically out of the box without initiating opportunistic resolution against external package repositories2.

## **Platform-by-Platform Use Case Analysis**

### **Serverless Environments**

#### **AWS Lambda**

Serverless deployment on AWS Lambda requires managing strict package size limits and execution environments across both x86\_64 and arm64 architectures4. Official AWS documentation establishes an uncompressed deployment package limit of 250 MB, which applies across the function code and all attached Lambda layers26. Direct zip uploads through the AWS API are constrained to 50 MB compressed, while larger archives must be staged through Amazon S326. Ephemeral disk storage in /tmp is configurable between 512 MB and 10,240 MB47.  
The primary platform constraint is filesystem mutability: the root execution directory (/var/task) and layer paths (/opt) are strictly read-only during runtime execution. Temporary storage in /tmp represents the only writable filesystem partition47. Furthermore, the AWS Lambda execution daemon does not launch scripts via standard python invocations; it initializes an internal runtime loop that imports a handler function using module syntax (e.g., lambda\_function.lambda\_handler)4.  
Today, developers typically package Lambda functions using pip install \-t into a staging folder, run multi-stage Docker builds using uv export, or deploy container images up to 10 GB4. Standard .pyz archives fail in Lambda if they attempt to extract compiled C extensions into default cache locations such as \~/.cache or adjacent directories, resulting in immediate read-only filesystem errors.  
To support AWS Lambda, a bundler must emit a flat, uncompressed .zip archive matching the platform's expected directory layout, or provide a .pyz runtime shim that explicitly redirects native extension extraction to /tmp/.cache. The bundler requires a dedicated \--target lambda preset that compiles native dependencies against the manylinux2014 target for the specified architecture. bundleup's fit for this domain is strong, provided it supports flat serverless zips or configurable extraction roots.

#### **Google Cloud Run Functions**

Google Cloud Run functions execute within managed container sandboxes that scale dynamically based on incoming HTTP requests or CloudEvents6. The platform enforces an uncompressed deployment archive limit of 512 MiB when deploying from source code49. The underlying filesystem allocates /tmp as an in-memory tmpfs partition, meaning storage consumed by temporary files directly depletes available container memory50. Instances support high concurrency, allowing up to 1,000 concurrent requests per container33.  
Standard deployment pipelines transmit raw source code alongside a requirements.txt file, triggering remote Google Cloud Buildpacks to compile dependencies51. This process introduces significant deployment latency and frequently encounters build timeouts when compiling heavy native extensions.  
An optimal artifact for Cloud Run functions is a pre-compiled flat archive that can be consumed directly by Cloud Run without invoking remote package resolution. The bundler must handle pure and compiled dependencies (Shapes B and C) locked against Linux x86\_64. bundleup demonstrates a strong fit by eliminating remote compilation overhead and accelerating cold start initialization.

#### **Azure Functions (Flex Consumption)**

Microsoft introduced the Azure Functions Flex Consumption hosting model to deliver elastic, Linux-based execution for event-driven functions31. The platform supports deployment packages up to 1 GB uncompressed, addressing previous constraints in legacy Consumption tiers52. Instances are provisioned with 512 MB (0.25 vCPU), 2,048 MB (1 vCPU), or 4,096 MB (2 vCPU) allocations5. Temporary storage in /tmp is capped at 0.8 GB, while persistent storage is unavailable31. Application initialization enforces a strict 30-second timeout, making cold-start initialization performance critical52. For Python workloads, HTTP trigger concurrency defaults to a single execution per instance54.  
Developers currently rely on Azure Functions Core Tools or remote builds powered by Oryx. Remote dependency builds regularly suffer from prolonged deployment times and intermittent package resolution failures.  
The optimal output format is a flat platform deployment archive containing pre-compiled wheels targeted to Linux x86\_64. A bundler must resolve all dependencies ahead of time, ensuring that application initialization completes well within the 30-second host timeout52. bundleup provides a strong fit by pre-building all application dependencies into a ready-to-run structure, bypassing remote Oryx builds entirely.

#### **Vercel Python Functions**

Vercel serverless functions host backend API endpoints backing frontend applications25. Official platform specifications set the standard uncompressed bundle size limit for Python functions at 500 MB, with Large Functions supporting up to 5 GB on Fluid Compute18. Execution durations default to 300 seconds, with extended durations up to 800 seconds available on paid tiers25. File execution is confined to ephemeral execution sandboxes where /tmp is the sole writable directory25.  
Vercel builds Python functions by reading requirements.txt or Pipfile during deployment56. Projects including large frameworks and compiled packages frequently exceed size thresholds or experience build timeouts during installation18.  
A flat serverless zip containing an integrated ASGI or WSGI entry point adapter fits this platform best. The bundler must prune unnecessary assets (such as test suites, documentation files, and static headers) to maintain bundle sizes within the 500 MB boundary25. bundleup's fit is partial; while it can build the underlying artifact, Vercel's build pipeline expects standard Git repository layouts and automated framework detection, requiring intermediate configuration shims.

#### **Cloudflare Python Workers**

Cloudflare Workers run Python workloads at the network edge by embedding Pyodide within the open-source workerd runtime7. The platform enforces an uncompressed worker bundle size limit of 64 MiB, alongside a strict memory limit of 128 MB per isolate13. The execution environment operates inside a WebAssembly sandbox, lacking an underlying Linux kernel, standard filesystem, or POSIX dynamic linker14.  
Applications are packaged using Wrangler, which bundles pure Python scripts and Pyodide-compatible wheels13. Standard compiled Linux wheels containing ELF shared objects (.so) fail immediately because the platform cannot execute native machine code17.  
This use case requires a specialized WebAssembly archive rather than an executable zipapp. It is out of scope for bundleup, which is fundamentally architected to target standard CPython interpreters running on POSIX and Windows operating systems.

### **Data and Batch Processing**

#### **PySpark, Databricks, and AWS EMR Jobs**

Apache Spark distributed clusters process massive datasets by executing Python code across hundreds or thousands of worker executor nodes8. Spark provides a native dependency distribution mechanism via the \--py-files command-line argument, which accepts .py, .zip, or .egg files, distributes them across the cluster network, and appends them to each executor's PYTHONPATH8. Worker nodes are frequently deployed in secure network zones without external internet access, preventing dynamic package installation during task execution42.  
The architectural challenge in Spark environments is that executor nodes load archives passed via \--py-files using standard CPython zipimport8. Consequently, any .zip archive containing native compiled C extensions fails with an immediate ImportError on worker nodes39. To run compiled dependencies like numpy or pyarrow, data teams are forced to configure heavyweight Conda environments, distribute monolithic tarballs using the \--archives parameter, or maintain custom Docker container images across cluster nodes40.  
The optimal output format is a data-platform zip for pure-Python code, or an executable .pyz equipped with an automated self-extraction routine that unpacks native shared libraries into the executor's local scratch directory (SPARK\_LOCAL\_DIRS). The bundler must handle pure and compiled dependencies (Shapes B and C). bundleup demonstrates an exceptionally strong fit for this ecosystem by providing a single file that can be passed directly to spark-submit \--py-files, bypassing the operational burden of managing cluster-wide Conda environments8.

#### **Ray Distributed Clusters**

Ray coordinates distributed computing and machine learning workloads across elastic compute clusters59. Ray provides dynamic environment provisioning through its runtime\_env API, allowing developers to define dependencies per-job, per-actor, or per-task41. Dependencies can be supplied as local directories or remote archives via the py\_modules and working\_dir configuration keys9. Ray enforces a 500 MiB limit on local working directory uploads41. Remote zip archives are downloaded by Ray workers and extracted into node-local scratch directories, which are then appended to the worker process PYTHONPATH41.  
When users define dependencies using runtime package lists (e.g., runtime\_env={"pip": \["requirements.txt"\]}), every worker node executes independent pip install commands during startup9. This introduces long task initialization delays, cluster-wide worker timeouts, and intermittent network failures caused by concurrent PyPI requests9.  
The ideal output format is a platform deployment zip. Ray's remote archive unpacker explicitly requires that the archive contain a single top-level directory whose contents are mapped to the working root9. The bundler must package locked dependencies into this single-directory archive layout. bundleup exhibits a strong fit, enabling zero-install, deterministic execution across distributed Ray actors44.

#### **Airflow and Dagster Orchestration Tasks**

Workflow orchestrators such as Apache Airflow and Dagster execute automated data pipelines where individual pipeline tasks frequently require conflicting library versions (for instance, an older database connector running alongside a modern analytics client). Orchestrator workers run inside long-lived processes or Kubernetes worker pods. While tools like Airflow's PythonVirtualenvOperator isolate tasks by building ephemeral virtual environments, this approach incurs substantial startup overhead on every task execution as dependencies are downloaded and installed dynamically.  
Data teams currently maintain sprawling Docker images containing all pipeline dependencies, or accept several minutes of task latency while ephemeral virtual environments are provisioned.  
The ideal output format is a self-contained .pyz archive that can be executed directly by worker tasks via python task\_bundle.pyz. The bundler must package pure and compiled dependencies (Shapes B and C) and extract native libraries into persistent or ephemeral worker caches. bundleup offers a strong fit, eliminating virtual environment creation overhead while maintaining strict dependency isolation between tasks.

#### **High-Performance Computing (HPC) Clusters**

HPC systems running Slurm, PBS, or LSF manage scientific computing workloads across thousands of compute nodes interconnected via parallel filesystems like Lustre, GPFS, or BeeGFS10. Compute nodes are isolated from external networks to ensure cluster stability and security. Parallel filesystems are architected for high-throughput sequential block operations, but experience severe performance degradation when subjected to metadata-intensive workloads, such as thousands of compute cores concurrently opening and scanning directories containing millions of individual .py and .pyc files10.  
Standard workflows involve creating large Conda or virtual environments on shared storage mounts. When thousands of MPI ranks or array tasks start simultaneously, the resulting metadata storm can overwhelm filesystem metadata servers, causing node hangs and cluster slowdowns10. HPC cluster administrators often mandate staging environments onto node-local RAM disks or local scratch storage (/tmp or \$SLURM\_TMPDIR) prior to execution10.  
A self-contained .pyz archive provides immediate operational benefits in this setting: it condenses an entire application and its dependency tree into a single file, eliminating millions of metadata lookups across shared storage mounts. The bundler must handle pure, compiled, and system-linked dependencies (Shapes B, C, and D), while offering configurable extraction paths to ensure native shared objects are unpacked into high-speed local scratch directories rather than the shared filesystem. bundleup is a strong fit for HPC workloads.

### **CI and Automation Systems**

#### **CI Scripts and GitHub Actions**

Continuous integration workflows on GitHub Actions, GitLab CI, and similar platforms rely heavily on Python automation scripts for tasks such as linting, compliance verification, and deployment orchestration. Standard virtual machine runners (ubuntu-latest, windows-latest) provide pre-installed Python interpreters, but lack pre-configured application dependencies.  
Pipelines routinely execute pip install or uv pip install on every job run3. This introduces external network dependencies, increases job runtimes, and exposes the build pipeline to flakiness caused by upstream package index outages.  
A standalone .pyz archive containing all necessary pure and compiled dependencies (Shapes B and C) provides a highly reliable alternative. The bundler must support deterministic, reproducible archive creation to maximize CI caching efficiency. bundleup has a strong fit here, enabling instant script execution without requiring virtual environment setup or network access.

#### **Pre-commit Hooks**

The pre-commit framework enforces code quality standards across developer workstations before changes are committed to version control. The framework manages hook isolation by cloning tool repositories and building dedicated virtual environments within local cache directories (\~/.cache/pre-commit/).  
Building these isolated virtual environments introduces a 10 to 45 second latency penalty the first time a hook is encountered, interrupting developer workflows and occasionally leading developers to bypass hook verification.  
Distributing pre-commit hooks as pre-compiled .pyz executables eliminates this setup delay entirely. The bundler must handle CLI entry points (Shape E) alongside pure and compiled dependencies (Shapes B and C). bundleup is a strong fit, delivering instant hook execution across varied developer workstations.

#### **Ansible Modules ("AnsiballZ") and System Configuration Agents**

Ansible executes configuration management tasks on remote hosts by assembling self-contained execution bundles on the control node, transmitting them over SSH, and executing them against the remote target's Python interpreter60. Target systems often operate in restricted network zones where internet access is unavailable62. Under Ansible's AnsiballZ architecture, the control node packages the target module and its ansible.module\_utils dependencies into an in-memory zip archive, wraps it in a base64-encoded Python bootstrap script, streams it to the remote interpreter over standard input, and executes it directly60.  
Ansible modules are generally restricted to standard library utilities and internal helpers because third-party dependencies must be pre-installed on managed nodes via separate tasks60.  
While Ansible's internal build pipeline is hardcoded into ansible-core, custom system administration agents and standalone orchestration utilities outside the Ansible ecosystem benefit directly from self-contained .pyz bundles60. The bundler must support pure and compiled dependencies (Shapes A, B, and C). bundleup's fit is partial for native Ansible modules due to tight coupling within ansible-core, but strong for independent configuration management agents and administrative toolsets.

### **Applications Embedding Python**

#### **Blender Add-ons**

Blender embeds a complete CPython interpreter to power its user interface, procedural modeling tools, and third-party add-on ecosystem11. Blender ships with a locked Python minor version (for instance, Python 3.11 in Blender 4.2)65. All installed add-ons execute within the host process memory space, sharing a single interpreter runtime; add-ons cannot run inside isolated virtual environments or separate sub-interpreters11.  
Add-on developers typically vendor third-party dependencies into an internal directory within the add-on package and append that directory to sys.path during initialization11. When two independent add-ons vendor different, incompatible versions of the same library (such as requests or pydantic), the first add-on to load claims the module in sys.modules, causing subtle bugs or runtime crashes in the other11. Furthermore, compiled extensions often fail if their ABI does not match Blender's bundled interpreter11.  
The optimal output format is a vendored directory (dir) combined with automated package shading (byte-level or source-level rewriting of module namespaces) to isolate the add-on's dependencies from other extensions in the shared interpreter11. The bundler must support pure and compiled dependencies (Shapes B and C) locked to the specific host Python ABI. bundleup has a strong fit for add-on packaging, provided it implements a directory output format.

#### **Splunk Applications**

Splunk Enterprise provides an embedded Python environment (\\(SPLUNK\_HOME/bin/splunk cmd python) to execute modular inputs, custom search commands, and custom REST API endpoints12. Splunk applications are distributed as compressed archives (.spl or .tar.gz) that unpack directly into \\)SPLUNK\_HOME/etc/apps//12. Third-party libraries must be placed into designated bin/ or lib/ directories and appended to sys.path dynamically12.  
Apps distributed through Splunkbase must pass Splunk AppInspect validation, an automated security and standards suite36. AppInspect inspects package directories and flags applications containing prohibited files, such as test fixtures, build artifacts, hidden directories, or unapproved binaries36. Developers running manual pip install \-t commands frequently see their packages rejected due to extraneous metadata files left behind by package installers.  
The optimal format is a clean, vendored directory (dir). The bundler must strip test directories, header files, and extraneous build metadata to pass AppInspect validation36. bundleup is a strong fit for Splunk app development, reducing packaging friction and ensuring clean directory structures.

#### **Visual Effects and Engineering Tools (Maya, Houdini, QGIS, ArcGIS)**

Professional VFX applications (Autodesk Maya, SideFX Houdini) and GIS suites (QGIS, ArcGIS Pro) embed Python runtimes to support automation, rigging, and geospatial modeling. The visual effects industry adheres to the annual VFX Reference Platform specification, which enforces exact CPython minor versions, C runtime libraries, and compiler versions across all DCC tools.  
Distributing plugins containing compiled dependencies into these platforms is notoriously complex. Users frequently lack administrative rights to install packages into the host application's core directories, and modifying global environment variables can destabilize other installed software.  
The ideal distribution artifact is an isolated vendored directory or a self-contained .pyz archive that extracts native components into an application-specific user cache directory. The bundler must target precise Python ABI configurations and handle compiled extensions (Shapes B and C). bundleup provides a strong fit, enabling clean plugin distribution without modifying host application installations.

#### **KNIME and Enterprise Analytics Platforms**

KNIME Analytics Platform integrates Python scripting nodes into graphical data science workflows37. While modern KNIME releases leverage Pixi and Conda to manage Python environments behind the scenes, workflows shared across teams frequently encounter missing or mismatched package environments on target machines27.  
KNIME provides Conda Environment Propagation nodes to capture and recreate dependency environments across machines71. However, recreating environments on target hosts introduces significant execution delays and requires outbound network access, which is often blocked in corporate settings73.  
A self-contained .pyz archive or portable environment pack containing pre-compiled wheels circumvents the need for target-side environment resolution. bundleup fits well here, providing standalone execution components that drop directly into enterprise workflow pipelines.

### **Corporate, Operational, and Edge Workloads**

#### **Internal Tools and Corporate CLIs**

Engineering organizations rely on hundreds of internal CLI utilities for deployment management, database synchronization, developer setup, and operational triage. Target workstations across an enterprise typically feature a base Python interpreter, but exhibit wide variance in local virtual environment configurations, package versions, and administrative permissions.  
Distributing these tools via private package indexes requires every end user to manage isolated virtual environments using tools like pipx1. Setup steps often fail on non-technical machines or misconfigured environments, creating ongoing support overhead for internal platform teams.  
A standalone .pyz archive is the ideal solution for this use case. It allows developers to distribute a single executable file that runs immediately via python tool.pyz, without requiring virtualenv creation or package installation steps1. The bundler must support multiple CLI subcommands (Shape E) and compiled extensions (Shapes B and C). This represents bundleup's primary sweet spot.

#### **Air-Gapped and Incident-Response Environments**

Cybersecurity incident response teams, forensic analysts, and defense contractors routinely operate within air-gapped server environments, SCADA networks, and isolated enclaves where external network connections are prohibited. Forensic standards require analysts to minimize system state modifications on analyzed endpoints, making traditional package installation operations unacceptable.  
Incident responders currently transfer collections of loose script files alongside directories of wheel archives, running fragile local installation routines, or rely on large, statically compiled binaries.  
A self-contained .pyz archive provides an ideal distribution mechanism for this domain. It packages all analysis routines and native dependencies into a single, verifiable artifact with a known cryptographic hash. The bundler must ensure the archive operates completely offline and extracts native extensions into memory-backed temporary paths (such as /dev/shm on Linux) to prevent unmanaged artifacts from remaining on the target filesystem. bundleup is an exceptionally strong fit for this workload.

#### **Edge and Embedded Devices**

Industrial edge gateways, environmental monitoring stations, and Raspberry Pi deployments operate on resource-constrained hardware over low-bandwidth or metered cellular connections. Devices frequently utilize read-only root filesystems to prevent flash memory corruption during power failures.  
Compiling native wheels directly on edge devices is unfeasible due to constrained CPU and memory resources. Conversely, distributing full container images over cellular links consumes excessive bandwidth and incurs high storage overhead.  
A compact .pyz archive containing cross-compiled native extensions for the target architecture (armv7l or aarch64) offers an optimal packaging model. The bundler must support cross-compilation targeting ARM architectures, with native extension extraction directed to an ephemeral RAM disk. bundleup represents a strong fit for embedded deployments where container overhead cannot be justified.

#### **Desktop Software for Non-Technical Users**

Consumer-facing desktop applications target non-technical users whose computers typically lack a pre-installed Python interpreter or the know-how to run command-line tools.  
Packaging software for this audience requires generating native OS executables (.exe, .app, or flatpak) that bundle a private Python interpreter, operating system graphical interface libraries, application icons, and platform code signatures (e.g., Apple Gatekeeper notarization and Windows Authenticode)2.  
A .pyz archive fails in this domain because it fundamentally requires a pre-existing host Python interpreter1. While tools like PyApp or scie-jump can wrap a .pyz alongside a standalone interpreter binary from python-build-standalone, building and signing full desktop application packages falls outside bundleup's architectural scope1. This use case is out of scope.

#### **Agent Sandboxes and Ephemeral Execution**

Modern artificial intelligence architectures leverage large language model agents to write and execute code inside ephemeral, short-lived sandboxes (such as Modal, E2B, or lightweight container runtimes). Because these sandboxes are provisioned dynamically for individual execution steps, startup latency directly impacts overall responsiveness and compute costs.  
Running dynamic pip install commands within ephemeral sandboxes adds multiple seconds to every execution cycle, significantly increasing latency.  
Distributing pre-bundled .pyz packages to sandbox environments allows execution to begin immediately. The bundler must generate lightweight archives with minimal extraction latency. bundleup is a strong fit for agent sandboxes, enabling rapid code execution without runtime package resolution.

#### **Education and Course Tooling**

Computer science courses and automated grading platforms (such as Gradescope) execute student code submissions across thousands of varied desktop and server environments. Novice students frequently encounter severe environment setup friction, struggling with shell paths, virtual environment activation, and operating system permission boundaries.  
Instructors spend considerable time debugging student environment configurations rather than teaching coursework.  
Packaging course assignments, testing harnesses, and interactive exercises as self-contained .pyz archives allows students to run assignments directly with a single command: python assignment.pyz. bundleup is an outstanding fit for educational settings, eliminating environment configuration hurdles entirely.

#### **Notebooks Converted to Production Jobs**

Data science teams frequently prototype analytical workflows within Jupyter Notebooks (.ipynb) and subsequently seek to operationalize them as scheduled batch processing routines.  
Notebooks accumulate untracked dependencies, implicit state, and undocumented execution ordering. Converting a notebook into a production script using tools like nbconvert generates raw Python source files, but leaves the underlying dependency environment unresolved.  
While a .pyz archive provides a robust target for executing the converted batch job, parsing and extracting dependencies directly from unstructured Jupyter Notebook metadata requires a specialized pre-processing step. bundleup exhibits a partial fit: it serves as an excellent packaging target once code and dependencies are codified into standard project formats, but should not attempt to handle notebook ingestion directly.

## **Workload Feasibility and Prioritization Matrix**

The matrix below maps each evaluated workload to its required input shapes, runtime environment constraints, optimal packaging format, and overall fit with bundleup's architecture.

| Workload Domain | Required Input Shapes | Target System Python | Optimal Output Format | Fit Assessment | Critical Architectural Requirement / Blocker |
| :---- | :---- | :---- | :---- | :---- | :---- |
| **AWS Lambda** | B, C | AWS Managed (3.10–3.13)4 | Flat Platform Zip (.zip)4 | **Strong** | Cache extraction must target writable /tmp; read-only /var/task breaks standard .pyz \[cite: 47\] |
| **Cloud Run Functions** | B, C | GCP Managed (3.10–3.12)6 | Flat Platform Zip (.zip)6 | **Strong** | Must bypass slow Cloud Buildpacks wheel compilation phase51 |
| **Azure Functions (Flex)** | B, C | Azure Managed (3.10–3.12)52 | Flat Platform Zip (.zip) | **Strong** | Must stay within 30s init timeout and operate within 0.8 GB /tmp limit31 |
| **Vercel Functions** | B, C | Vercel Managed (3.10–3.12)25 | Flat Platform Zip (.zip) | **Partial** | Must stay under 500 MB uncompressed limit and interface with WSGI/ASGI handlers25 |
| **Cloudflare Workers** | B, (C as Wasm) | Pyodide / Emscripten13 | WebAssembly Bundle | **Out of Scope** | Lacks host Linux/CPython runtime; native .so files fail completely17 |
| **PySpark / Databricks** | B, C | Cluster Image Managed42 | Data Platform Zip / Flat Zip8 | **Strong** | Standard zipimport breaks native wheels unless custom extraction hook is used39 |
| **Ray Distributed Clusters** | B, C | Cluster Image Managed41 | Platform Zip (.zip)44 | **Strong** | Zip must contain single root folder for Ray remote URI unpacker compatibility9 |
| **Airflow / Dagster Tasks** | B, C | Host / Worker Container | Standalone .pyz | **Strong** | Direct execution eliminates dynamic virtual environment creation delays |
| **HPC Slurm Clusters** | B, C, D | Host Module Python | Standalone .pyz \[cite: 10\] | **Strong** | Solves Lustre shared filesystem metadata bottleneck; cache must point to local scratch10 |
| **CI / GitHub Actions** | B, C | Runner System Python | Standalone .pyz | **Strong** | Eliminates flaky pip install phases during pipeline execution3 |
| **Pre-commit Hooks** | B, C | Developer Host Python | Standalone .pyz | **Strong** | Bypasses 15–45s virtual environment creation delays during git commit routines |
| **Ansible / SysAdmin Agents** | A, B, C | Managed Host Python62 | Standalone .pyz \[cite: 60, 61\] | **Partial** | AnsiballZ pipeline is internal; external modules benefit via single-file payloads60 |
| **Blender Addons** | B, C | Embedded Python (3.11)65 | Vendored Directory (dir)11 | **Strong** | Needs directory export with import namespace isolation to prevent addon collisions11 |
| **Splunk Apps** | B, C | Embedded Splunk Python12 | Vendored Directory (dir)12 | **Strong** | Requires directory export stripped of testing and build metadata for AppInspect36 |
| **VFX (Maya / Houdini)** | B, C | Embedded VFX Python | Vendored Directory (dir) | **Strong** | Must lock dependencies against strict VFX Reference Platform ABI requirements |
| **Internal Tools & CLIs** | B, C | User Workstation Python | Standalone .pyz | **Strong** | Core target; eliminates user virtualenv management friction |
| **Air-gapped / Forensics IR** | B, C | Target System Python | Standalone .pyz | **Strong** | Zero-network operation; self-contained utility leaves no package footprint on target |
| **Edge / Embedded Devices** | B, C | Target Embedded Linux | Standalone .pyz | **Strong** | Requires cross-compilation support for target architectures (aarch64, armv7l) |
| **Desktop Non-Technical** | B, C, D | Missing (No Python)2 | Native Executable (exe/app)2 | **Out of Scope** | Requires embedding full interpreter, GUI frameworks, and OS code-signing2 |
| **Agent Sandboxes** | B, C | Minimal Base Container | Standalone .pyz | **Strong** | Enables sub-second cold starts for ephemeral tool execution |
| **Education / Grading** | B, C | Student Machine Python | Standalone .pyz | **Strong** | Delivers zero-friction script execution for introductory students |
| **Notebooks to Scripts** | B, C | Data Science Environment | Standalone .pyz | **Partial** | Requires pre-processing to extract clean dependency graphs from unstructured notebooks |

## **Bundler Output Strategy and CLI Architecture**

### **Analysis of Neighboring Build Tools**

Examining successful build and packaging tools across the broader software ecosystem reveals distinct patterns in handling multiple compilation targets and output formats:

* **esbuild (--format, \--platform):** esbuild maintains an orthogonal separation between the code packaging standard (--format=esm|cjs|iife) and the target environment (--platform=browser|node|neutral). This design prevents combinatorial explosions in the CLI: the format governs module syntax conventions, while the platform flag determines global variable availability and default library resolution paths.  
* **Bun (bun build vs bun build \--compile):** Bun maintains a distinct boundary between bundling JavaScript code (bun build, which outputs clean, bundled JS assets) and compiling standalone native executables (bun build \--compile, which embeds the Bun runtime executable alongside the application code). This prevents users from confusing lightweight script distribution with standalone native compilation.  
* **Deno (deno compile):** Following a similar pattern, Deno establishes a dedicated top-level subcommand for generating self-contained native executables, keeping it distinct from code execution (deno run) and module bundling.  
* **PEX:** PEX exposes deep configuration capabilities via numerous CLI flags, including \--venv, \--sh-boot, and \--scie20. However, the proliferation of interdependent, low-level control knobs creates significant cognitive friction for developers, making it difficult to determine the correct flag combinations for a given deployment target.  
* **PyInstaller (--onefile vs \--onedir):** PyInstaller illustrates the operational trade-offs of physical artifact layouts2. The \--onedir layout starts instantly because all files are directly available to the OS loader, whereas \--onefile uncompresses all assets into a temporary directory on each launch, incurring noticeable startup overhead2.  
* **The .NET CLI (dotnet publish):** The .NET ecosystem manages output complexity through declarative project properties and publishing presets (e.g., \-p:PublishSingleFile=true, \--self-contained). This model provides sensible defaults out of the box while exposing granular levers when specific deployment optimizations are required.

### **Evaluating Multi-Format Expansion vs. a Dedicated .pyz Engine**

A critical strategic question for bundleup is whether to expand across multiple artifact formats or focus exclusively on .pyz execution.  
The argument for focusing exclusively on .pyz is compelling: the technical challenges of runtime import interception, zip-safety emulation, cross-platform native library extraction, and cache management for compiled extensions are substantial16. Perfecting this execution pipeline across varied operating systems, C runtimes, and Python versions provides tremendous value. Attempting to generate OCI container images, WebAssembly modules, and platform native executables risks transforming a lightweight, fast bundler into an unwieldy platform with high ongoing maintenance costs1.  
However, strict adherence to .pyz as the sole output format fundamentally cuts the tool off from major production environments:

> 1. **Serverless environments (AWS Lambda, Azure Functions):** As established, the root filesystems of these platforms are mounted read-only31. Executing a standard .pyz that attempts to unpack native extensions into adjacent directories will crash with filesystem errors47. Serving these platforms requires either a flat, uncompressed archive or an extraction hook configured specifically for ephemeral partitions4.  
> 2. **Host-embedded runtimes (Blender, Splunk, QGIS):** These platforms load plugins by discovering loose directory structures on the filesystem11. They do not execute external .pyz applications directly11.

The optimal architectural balance is to retain .pyz as the core execution format, while offering a small, tightly bounded set of physical layout variations:

* **pyz (default):** An executable zip archive with self-extracting cache management for compiled extensions15.  
* **zip:** A flat deployment zip archive containing pre-compiled, uncompressed dependencies laid out directly on sys.path, intended for serverless platforms and PySpark jobs4.  
* **dir:** A clean vendored directory containing pre-compiled dependencies with unnecessary metadata stripped, designed for host application plugins and container layer assembly3.

Standalone native executables that embed a full CPython interpreter runtime should be delegated to specialized downstream tools (such as PyApp, scie-jump, or PyInstaller) via composable build pipelines, rather than built directly into bundleup2.

### **Recommended CLI Grammar**

The CLI design should combine explicit, orthogonal format flags with high-level target presets that bundle sensible defaults:

bundleup build \[PATH\] \[OPTIONS\]

Core Output Formatting:  
  \-f, \--format        Output artifact structure (default: pyz)  
                                     pyz: Executable zipapp with native extraction cache  
                                     zip: Flat deployment archive (for Lambda, Cloud Run, Spark)  
                                     dir: Vendored directory (for Blender, Splunk, plugins)  
  \-o, \--output               Destination output file or directory path

High-Level Target Presets (Shorthand profiles configuring format, extraction paths, and platforms):  
  \--target                 Pre-configured target profile:  
                                     lambda    \-\> \--format zip \--platform manylinux2014\_x86\_64  
                                     spark     \-\> \--format zip \--pure-python  
                                     blender   \-\> \--format dir \--clean-metadata  
                                     splunk    \-\> \--format dir \--clean-metadata

Cross-Compilation & Target Platform Flags:  
  \--platform                  Target platform tag (e.g., manylinux2014\_x86\_64, macosx\_11\_0\_arm64)  
  \--python-version        Target Python ABI version (e.g., cp311, cp312)

Cache & Extraction Mechanics (for .pyz format):  
  \--cache-dir            Native extension cache location: 'temp', 'home', or explicit path  
  \--entry-point            Execution target override (module:function or console script name)

## **Workload Strategic Horizons**

### **Advertise Now**

These workloads function out of the box using bundleup's core .pyz format on machines with compatible Python runtimes:

* Continuous integration scripts and GitHub Actions runners3  
* Internal engineering command-line utilities and administrative scripts  
* Air-gapped operational tools and cybersecurity incident-response utilities  
* Computer science coursework, assignments, and automated grading suites  
* Standalone Airflow and Dagster data pipeline task execution  
* Ephemeral AI agent sandboxes and tool execution environments

### **Support Soon**

These workloads require specific near-term features—such as configurable cache extraction paths, flat directory exports, or target platform cross-compilation—before they can be fully supported:

* **AWS Lambda and Azure Functions Flex Consumption:** Requires flat archive output (--format zip) or explicit cache redirection to /tmp to support read-only root filesystems31.  
* **Apache Spark Cluster Jobs:** Requires flat archive packaging (--format zip) or an automated worker self-extraction hook to enable compiled native extensions over \--py-files8.  
* **Ray Distributed Workloads:** Requires packaging archives with a single top-level root directory to ensure compatibility with Ray's remote archive unpacker9.  
* **High-Performance Computing (HPC) Nodes:** Requires configuring cache extraction paths to local scratch partitions (e.g., \$SLURM\_TMPDIR) to prevent Lustre filesystem metadata bottlenecks10.  
* **Host Application Plugins (Blender, Splunk, QGIS):** Requires a directory output format (--format dir) with automated metadata stripping to comply with host plugin standards11.

### **Out of Scope**

These workloads require fundamentally distinct execution architectures and should be explicitly excluded from bundleup's development roadmap:

* **Standalone Desktop Applications for Non-Technical Users:** Requires embedding private CPython interpreter binaries, windowing system hooks, and OS code-signing certifications; best addressed by PyApp, scie-jump, or PyInstaller2.  
* **Cloudflare Python Workers:** Requires WebAssembly compilation and integration with the Pyodide/V8 execution model, which cannot load standard Linux ELF wheels or CPython dynamic libraries13.  
* **Applications Dependent on Non-Python System Runtimes (Shape D):** Managing arbitrary system binaries, external browser distributions, or host CUDA driver stacks requires full operating system containerization (Docker, Podman)3.

## **Documentation Invitation Statements**

### **CI/CD and Automation Engineers**

Eliminate flaky package installations and accelerate execution across your CI pipelines. bundleup packages your locked Python automation scripts into a single, deterministic .pyz archive that executes immediately on any runner with Python installed, requiring no virtual environment setup or network calls3.

### **Internal Tools and Platform Developers**

Distribute internal CLI utilities to your team without virtual environment friction, broken paths, or missing dependencies. Ship a single self-contained executable file that runs reliably across workstations straight out of the box.

### **Incident Responders and Security Analysts**

Deploy forensic and triage tools into air-gapped or compromised environments with zero network overhead. bundleup builds hermetic, locked single-file utilities that execute without installing packages or leaving unmanaged files across target filesystems.

### **Educators and Course Instructors**

Distribute programming assignments and automated grading suites that run instantly on student laptops. bundleup provides students with a single executable file, eliminating virtual environment configuration hurdles and environment debugging during class.

### **Data Orchestration Teams (Airflow and Dagster)**

Prevent dependency conflicts across pipeline tasks without maintaining dozens of heavy container images. Package individual workflow steps into standalone .pyz files that execute cleanly across shared worker clusters.

### **AI Agent Sandbox Developers**

Achieve sub-second cold starts for code-interpreting agents in ephemeral execution sandboxes. bundleup packages your locked toolsets into standalone archives that run instantly, bypassing runtime package installation latency.

### **AWS Lambda and Serverless Practitioners**

Build ultra-lean serverless deployment packages that bypass slow container cold starts4. bundleup packages your application code and pre-compiled wheels into optimized serverless archives configured to operate smoothly within Lambda's read-only filesystem boundaries47.

### **Data Engineers (PySpark and Databricks)**

Distribute Python dependencies across thousands of Spark executor nodes using standard \--py-files workflows8. bundleup packages your project into a cluster-ready archive that executes reliably across remote workers without runtime package downloads42.

### **Distributed AI Engineers (Ray)**

Accelerate Ray task scheduling and avoid runtime package installation timeouts across worker nodes9. bundleup emits locked, pre-resolved archives designed for instant distribution via Ray's runtime\_env API9.

### **HPC Systems Researchers**

Eliminate filesystem metadata contention on Lustre and GPFS parallel filesystems during large-scale Python runs10. bundleup consolidates thousands of library files into a single archive engineered to execute out of node-local scratch storage10.

### **Blender Add-on and Host Application Developers**

Vendor third-party wheels into your Blender add-on, Splunk app, or QGIS plugin without brittle manual installation hacks11. bundleup exports clean, pre-compiled dependency directories structured to isolate imports and pass strict platform validation suites11.

#### **Works cited**

> 1. virtualenv(1) — Arch manual pages, [https\://man.archlinux.org/man/virtualenv.1.en](https://man.archlinux.org/man/virtualenv.1.en)  
> 2. \`uv bundle\`, \`uv build \--release\` or similar to create a contained, [https\://github.com/astral-sh/uv/issues/5802](https://github.com/astral-sh/uv/issues/5802)  
> 3. Building Container Images Without Docker: Introducing pycontainer, [https\://dev.to/spboyer/building-container-images-without-docker-introducing-pycontainer-build-5go7](https://dev.to/spboyer/building-container-images-without-docker-introducing-pycontainer-build-5go7)  
> 4. Using uv with AWS Lambda \- Astral Docs, [https\://docs.astral.sh/uv/guides/integration/aws-lambda/](https://docs.astral.sh/uv/guides/integration/aws-lambda/)  
> 5. Migrating Azure Functions from Linux Consumption to Flex ... \- Medium, [https\://medium.com/villa-plus-engineering/migrating-azure-functions-from-linux-consumption-to-flex-consumption-c10b118c0c85](https://medium.com/villa-plus-engineering/migrating-azure-functions-from-linux-consumption-to-flex-consumption-c10b118c0c85)  
> 6. Google Cloud Run Production-Operations Guide: Container, [https\://tomodahinata.com/en/blog/google-cloud-run-production-guide](https://tomodahinata.com/en/blog/google-cloud-run-production-guide)  
> 7. Python Workers redux: fast cold starts, packages, and a uv-first, [https\://blog.cloudflare.com/python-workers-advancements/](https://blog.cloudflare.com/python-workers-advancements/)  
> 8. Submitting Applications \- Spark 4.2.0 Documentation \- Apache Spark, [https\://spark.apache.org/docs/latest/submitting-applications.html](https://spark.apache.org/docs/latest/submitting-applications.html)  
> 9. 环境依赖— Ray 2.53.0, [https\://docs.rayai.org.cn/en/latest/ray-core/handling-dependencies.html](https://docs.rayai.org.cn/en/latest/ray-core/handling-dependencies.html)  
> 10. Stage a Conda Environment on Local Disk \- GitHub, [https\://github.com/HenrikBengtsson/conda-stage](https://github.com/HenrikBengtsson/conda-stage)  
> 11. python \- Using venv with Blender?, [https\://blender.stackexchange.com/questions/336743/using-venv-with-blender](https://blender.stackexchange.com/questions/336743/using-venv-with-blender)  
> 12. Use the Extensible Administration Interface \- Splunk Dev, [https\://dev.splunk.com/enterprise/docs/devtools/customrestendpoints/customresteai](https://dev.splunk.com/enterprise/docs/devtools/customrestendpoints/customresteai)  
> 13. Cloudflare Workers in September 2026: What Changed This Week, [https\://medium.com/@andriipap/cloudflare-workers-in-september-2026-what-changed-this-week-3b304218ccaf](https://medium.com/@andriipap/cloudflare-workers-in-september-2026-what-changed-this-week-3b304218ccaf)  
> 14. Python Cloudflare Workers \- Hacker News, [https\://news.ycombinator.com/item?id=39905441](https://news.ycombinator.com/item?id=39905441)  
> 15. Wishlist: make uv run \--script shebang also work for zipapp .pyz files, [https\://github.com/astral-sh/uv/issues/18662](https://github.com/astral-sh/uv/issues/18662)  
> 16. Provide uv zipapp · Issue \#7419 · astral-sh/uv \- GitHub, [https\://github.com/astral-sh/uv/issues/7419](https://github.com/astral-sh/uv/issues/7419)  
> 17. mbachry/exxo: Build portable Python binaries \- GitHub, [https\://github.com/mbachry/exxo](https://github.com/mbachry/exxo)  
> 18. "Serverless Function has exceeded the unzipped maximum size of, [https\://vercel.com/kb/guide/troubleshooting-function-250mb-limit](https://vercel.com/kb/guide/troubleshooting-function-250mb-limit)  
> 19. Self-contained highly-portable Python distributions | Hacker News, [https\://news.ycombinator.com/item?id=49073942](https://news.ycombinator.com/item?id=49073942)  
> 20. pex\_binary \- Pantsbuild, [https\://www\.pantsbuild.org/dev/reference/targets/pex\_binary](https://www.pantsbuild.org/dev/reference/targets/pex_binary)  
> 21. What's New in Python 2.5 — Python 3.14.8 documentation, [https\://docs.python.org/3/whatsnew/2.5.html](https://docs.python.org/3/whatsnew/2.5.html)  
> 22. PEX runtime environment variables \- Pex Docs (v2.101.1), [https\://docs.pex-tool.org/api/vars.html](https://docs.pex-tool.org/api/vars.html)  
> 23. Liberica NIK 23.0.0+1-20.0.1b10 Release Notes \- Bellsoft Docs, [https\://docs.bell-sw.com/liberica-nik/23.0.0b1-20.0.1b10/general/release-notes/](https://docs.bell-sw.com/liberica-nik/23.0.0b1-20.0.1b10/general/release-notes/)  
> 24. PyOxidizer \- Release 0.23.0 Gregory Szorc, [https\://pyoxidizer.readthedocs.io/\_/downloads/en/stable/pdf/](https://pyoxidizer.readthedocs.io/_/downloads/en/stable/pdf/)  
> 25. Vercel Functions Limits, [https\://vercel.com/docs/functions/limitations](https://vercel.com/docs/functions/limitations)  
> 26. AI Deployment: Why Serverless is Perfect (and Terrible), [https\://dev.to/gerimate/ai-deployment-why-serverless-is-perfect-and-terrible-4phl](https://dev.to/gerimate/ai-deployment-why-serverless-is-perfect-and-terrible-4phl)  
> 27. The Pixi Backend | KNIME Documentation, [https\://docs.knime.com/ap/latest/python\_installation\_guide/explanation/modern-backend](https://docs.knime.com/ap/latest/python_installation_guide/explanation/modern-backend)  
> 28. What is best practices for short scripts with venvs/uv? \- Reddit, [https\://www\.reddit.com/r/learnpython/comments/1oydalk/what\_is\_best\_practices\_for\_short\_scripts\_with/](https://www.reddit.com/r/learnpython/comments/1oydalk/what_is_best_practices_for_short_scripts_with/)  
> 29. A year of uv: pros, cons, and should you migrate | Hacker News, [https\://news.ycombinator.com/item?id=43095157](https://news.ycombinator.com/item?id=43095157)  
> 30. uv | Python Tools, [https\://realpython.com/ref/tools/uv/](https://realpython.com/ref/tools/uv/)  
> 31. Azure Functions Scale and Hosting | Microsoft Learn, [https\://learn.microsoft.com/en-us/azure/azure-functions/functions-scale](https://learn.microsoft.com/en-us/azure/azure-functions/functions-scale)  
> 32. Three Image Builders to Try While You're Waiting on 'docker build' to, [https\://blog.tilt.dev/2021/11/12/docker-build-alternatives.html](https://blog.tilt.dev/2021/11/12/docker-build-alternatives.html)  
> 33. Fargate vs Cloud Run vs Container Apps: \$30/Mo Gap \[2026\], [https\://shattered.io/fargate-vs-cloud-run-vs-container-apps-2026/](https://shattered.io/fargate-vs-cloud-run-vs-container-apps-2026/)  
> 34. Build Go containers with Ko \- Chainguard Academy, [https\://edu.chainguard.dev/chainguard/containers/building-and-modifying/build-tools/building-go-containers-with-ko/](https://edu.chainguard.dev/chainguard/containers/building-and-modifying/build-tools/building-go-containers-with-ko/)  
> 35. pex/CHANGES.md at main · pex-tool/pex \- GitHub, [https\://github.com/pex-tool/pex/blob/main/CHANGES.md](https://github.com/pex-tool/pex/blob/main/CHANGES.md)  
> 36. What's new in Splunk AppInspect CLI, [https\://dev.splunk.com/enterprise/docs/relnotes/relnotes-appinspectcli/whatsnew](https://dev.splunk.com/enterprise/docs/relnotes/relnotes-appinspectcli/whatsnew)  
> 37. Bundled Packages \- KNIME Documentation, [https\://docs.knime.com/ap/latest/python\_installation\_guide/reference/bundled-packages](https://docs.knime.com/ap/latest/python_installation_guide/reference/bundled-packages)  
> 38. Deep Learning Installation Guide | KNIME Documentation, [https\://docs.knime.com/ap/latest/deep\_learning\_installation\_guide/](https://docs.knime.com/ap/latest/deep_learning_installation_guide/)  
> 39. Hadoop Service (UHadoop) \- ViCloud, [https\://docs.vicloud.vn/docs/uhadoop/developer/sparkdev](https://docs.vicloud.vn/docs/uhadoop/developer/sparkdev)  
> 40. Set up a Spark on MaxCompute development environment on Linux, [https\://www\.alibabacloud.com/help/en/maxcompute/set-up-a-linux-development-environment](https://www.alibabacloud.com/help/en/maxcompute/set-up-a-linux-development-environment)  
> 41. Environment Dependencies — Ray 2.58.0, [https\://docs.ray.io/en/latest/ray-core/handling-dependencies.html](https://docs.ray.io/en/latest/ray-core/handling-dependencies.html)  
> 42. Managing Python dependencies for Spark workloads in ... \- Cloudera, [https\://www\.cloudera.com/blog/technical/managing-python-dependencies-for-spark-workloads-in-cloudera-data-engineering.html](https://www.cloudera.com/blog/technical/managing-python-dependencies-for-spark-workloads-in-cloudera-data-engineering.html)  
> 43. Configuration \- Spark 4.2.0 Documentation \- Apache Spark, [https\://spark.apache.org/docs/latest/configuration.html](https://spark.apache.org/docs/latest/configuration.html)  
> 44. RuntimeEnv — Ray 2.59.0 \- Ray Docs, [https\://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime\_env.RuntimeEnv.html](https://docs.ray.io/en/latest/ray-core/api/doc/ray.runtime_env.RuntimeEnv.html)  
> 45. serious\_python changelog | Flutter package \- Pub.dev, [https\://pub.dev/packages/serious\_python/changelog](https://pub.dev/packages/serious_python/changelog)  
> 46. Episode \#497 Faster than light profiling \- Python Bytes Podcast, [https\://pythonbytes.fm/episodes/show/497/faster-than-light-profiling](https://pythonbytes.fm/episodes/show/497/faster-than-light-profiling)  
> 47. Top 13 AWS Lambda Alternatives For Serverless Computing, [https\://www\.cloudzero.com/blog/lambda-alternatives/](https://www.cloudzero.com/blog/lambda-alternatives/)  
> 48. AWS Glue first experience \- part 2 \- Dependencies and guts, [https\://dev.to/1oglop1/aws-glue-first-experience-part-2-dependencies-and-guts-29l](https://dev.to/1oglop1/aws-glue-first-experience-part-2-dependencies-and-guts-29l)  
> 49. CloudGauge/README.md at main \- GitHub, [https\://github.com/GoogleCloudPlatform/CloudGauge/blob/main/README.md](https://github.com/GoogleCloudPlatform/CloudGauge/blob/main/README.md)  
> 50. Package google.cloud.run.v2 \- Google Cloud Documentation, [https\://docs.cloud.google.com/run/docs/reference/rpc/google.cloud.run.v2](https://docs.cloud.google.com/run/docs/reference/rpc/google.cloud.run.v2)  
> 51. Ship your Go applications faster to Cloud Run with ko, [https\://cloud.google.com/blog/topics/developers-practitioners/ship-your-go-applications-faster-cloud-run-ko](https://cloud.google.com/blog/topics/developers-practitioners/ship-your-go-applications-faster-cloud-run-ko)  
> 52. Scaling Azure Functions: Consumption vs Premium vs Dedicated, [https\://dev.to/martin\_oehlert/scaling-azure-functions-consumption-vs-premium-vs-dedicated-2gm](https://dev.to/martin_oehlert/scaling-azure-functions-consumption-vs-premium-vs-dedicated-2gm)  
> 53. Azure Functions Flex Consumption plan hosting \- Microsoft Learn, [https\://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan)  
> 54. Concurrency in Azure Functions \- Microsoft Learn, [https\://learn.microsoft.com/en-us/azure/azure-functions/functions-concurrency](https://learn.microsoft.com/en-us/azure/azure-functions/functions-concurrency)  
> 55. Python Vercel Functions bundle size limit increased to 500MB, [https\://vercel.com/changelog/python-vercel-functions-bundle-size-limit-increased-to-500mb](https://vercel.com/changelog/python-vercel-functions-bundle-size-limit-increased-to-500mb)  
> 56. Using the Python Runtime with Vercel Functions, [https\://vercel.com/docs/functions/runtimes/python](https://vercel.com/docs/functions/runtimes/python)  
> 57. Error: A Serverless Function has exceeded the unzipped maximum, [https\://medium.com/@anandmanash321/error-a-serverless-function-has-exceeded-the-unzipped-maximum-size-of-250-mb-990af9b2346d](https://medium.com/@anandmanash321/error-a-serverless-function-has-exceeded-the-unzipped-maximum-size-of-250-mb-990af9b2346d)  
> 58. How to Resolve 'Serverless Function Exceeded 250 MB' Error on, [https\://stackoverflow.com/questions/76734575/how-to-resolve-serverless-function-exceeded-250-mb-error-on-vercel-deployment](https://stackoverflow.com/questions/76734575/how-to-resolve-serverless-function-exceeded-250-mb-error-on-vercel-deployment)  
> 59. 环境依赖— Ray 2.37.0, [https\://www\.aidoczh.com/ray/ray-core/handling-dependencies.html](https://www.aidoczh.com/ray/ray-core/handling-dependencies.html)  
> 60. Ansible module architecture, [https\://docs.ansible.com/projects/ansible/latest/dev\_guide/developing\_program\_flow\_modules.html](https://docs.ansible.com/projects/ansible/latest/dev_guide/developing_program_flow_modules.html)  
> 61. Ansible yum throwing future feature annotations is not defined, [https\://stackoverflow.com/questions/78990297/ansible-yum-throwing-future-feature-annotations-is-not-defined](https://stackoverflow.com/questions/78990297/ansible-yum-throwing-future-feature-annotations-is-not-defined)  
> 62. Ansible: Up and Running, [https\://digtvbg.com/files/LINUX/Meijer%20B.%20Ansible.%20Up%20and%20Running...3ed%202022.pdf](https://digtvbg.com/files/LINUX/Meijer%20B.%20Ansible.%20Up%20and%20Running...3ed%202022.pdf)  
> 63. Ansible 2.2 Documentation \- Read the Docs, [https\://readthedocs.org/projects/ansible-doc-zh/downloads/pdf/latest/](https://readthedocs.org/projects/ansible-doc-zh/downloads/pdf/latest/)  
> 64. intersphinx untangled: docs.ansible.com, [https\://webknjaz.github.io/intersphinx-untangled/docs.ansible.com/](https://webknjaz.github.io/intersphinx-untangled/docs.ansible.com/)  
> 65. launch PIP from inside blender \-\>get dependancies from local path?, [https\://blenderartists.org/t/launch-pip-from-inside-blender-get-dependancies-from-local-path/670627](https://blenderartists.org/t/launch-pip-from-inside-blender-get-dependancies-from-local-path/670627)  
> 66. Maintaining Import Structure for Shared Modules in Blender 4.2, [https\://blender.stackexchange.com/questions/322355/maintaining-import-structure-for-shared-modules-in-blender-4-2-extensions](https://blender.stackexchange.com/questions/322355/maintaining-import-structure-for-shared-modules-in-blender-4-2-extensions)  
> 67. Addon absolute imports not working for local packages, [https\://blenderartists.org/t/addon-absolute-imports-not-working-for-local-packages/1556366](https://blenderartists.org/t/addon-absolute-imports-not-working-for-local-packages/1556366)  
> 68. Tools for developing and testing modular inputs | Enterprise, [https\://dev.splunk.com/enterprise/docs/developapps/manageknowledge/custominputs/modinputstools](https://dev.splunk.com/enterprise/docs/developapps/manageknowledge/custominputs/modinputstools)  
> 69. Develop a KNIME Extension with Python, [https\://docs.knime.com/developers/latest/create\_a\_node\_with\_python/](https://docs.knime.com/developers/latest/create_a_node_with_python/)  
> 70. Set up Conda / Miniforge \- KNIME Documentation, [https\://docs.knime.com/ap/latest/python\_installation\_guide/env-management/conda-setup](https://docs.knime.com/ap/latest/python_installation_guide/env-management/conda-setup)  
> 71. Python Installation Guide \- KNIME Documentation, [https\://docs.knime.com/ap/latest/python\_installation\_guide/](https://docs.knime.com/ap/latest/python_installation_guide/)  
> 72. Conda Environment Propagation Node \- KNIME Documentation, [https\://docs.knime.com/ap/latest/python\_installation\_guide/env-management/conda-propagation](https://docs.knime.com/ap/latest/python_installation_guide/env-management/conda-propagation)  
> 73. R Installation Guide | KNIME Documentation, [https\://docs.knime.com/ap/latest/r\_installation\_guide/](https://docs.knime.com/ap/latest/r_installation_guide/)