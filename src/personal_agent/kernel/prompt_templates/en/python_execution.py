"""English Python execution tool and parameter instructions."""

from personal_agent.kernel.prompt_registry import PromptTranslation


TRANSLATIONS = {
    "python_execution.description": PromptTranslation(
        'v5-artifact-id-inputs-md1', 'v5-artifact-id-inputs-en.1-md1',
        """

## Execution
Execute the Python code you submit and return its output and execution status. Each execution is independent; variables are not retained. Use print to produce output; a final expression is not returned automatically.

## Input files
sys.argv[1] is the read-only input directory, and each input_files entry corresponds to its name within that directory; omitting input_files means there are no input files. To reuse an existing program, bind its original artifact as an input file and read it in code or run it with runpy.run_path(..., run_name="__main__"); sys.argv[1] remains the input directory.

## Environment and result boundaries
Use the standard library and installed libraries in the fixed image. Network access and dependency installation are prohibited. Return the actual process status, exit code, diagnostics, and original artifact references for the program, input manifest, stdout, and stderr. Previews are bounded; read the originals for more content. If the terminal state is unknown, check the original execution first. Success only means the program ran; you decide the analysis method and subsequent actions.""",
    ),
    "python_execution.parameter.code": PromptTranslation(
        "v4-artifact-id-inputs", "v4-artifact-id-inputs-en.1",
        "Complete Python source code for this execution, run as a file; use print to produce output. At most 128 KiB.",
    ),
    "python_execution.parameter.input_files": PromptTranslation(
        "v4-artifact-id-inputs", "v4-artifact-id-inputs-en.1",
        "Optional list of read-only input files; defaults to [] when omitted. Each entry provides name and the resource_id of a currently readable file. Code reads each name from the sys.argv[1] directory; files are not discovered automatically. At most 32 entries and 64 MiB in total.",
    ),
    "python_execution.parameter.input_name": PromptTranslation(
        "v4-artifact-id-inputs", "v4-artifact-id-inputs-en.1",
        "This Artifact's flat filename in the read-only input directory; it must match the name used by the code. 1–64 characters, using only ASCII letters, digits, underscores, hyphens, and dots. Paths, trailing dots, case-insensitive duplicate names, Windows device names, program.py, and input_manifest.json are prohibited.",
    ),
    "python_execution.parameter.input_resource_id": PromptTranslation(
        "v4-artifact-id-inputs", "v4-artifact-id-inputs-en.1",
        "The string value of resource_ref.resource_id from supplied materials or a successful tool result. Runtime restores the full reference and mounts the original bytes read-only; do not pass a full object or a host path.",
    ),
}
