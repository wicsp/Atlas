import subprocess
from pathlib import Path
from types import SimpleNamespace

from atlas import system


def test_home_usage_parses_du_output_and_sorts_by_size(monkeypatch, tmp_path) -> None:
    (tmp_path / "alice").mkdir()
    (tmp_path / "bob").mkdir()

    def fake_disk_usage(path):
        assert path == str(tmp_path)
        return SimpleNamespace(total=1_000, used=400, free=600, percent=40.0)

    def fake_run(args, **kwargs):
        assert args == [
            "du",
            "-sB1",
            "--",
            str(tmp_path / "alice"),
            str(tmp_path / "bob"),
        ]
        return SimpleNamespace(
            stdout=f"250\t{tmp_path / 'alice'}\n500\t{tmp_path / 'bob'}\n"
        )

    monkeypatch.setattr(system.psutil, "disk_usage", fake_disk_usage)
    monkeypatch.setattr(system.subprocess, "run", fake_run)

    usage = system.get_home_usage(Path(tmp_path))

    assert [item.user for item in usage] == ["bob", "alice"]
    assert usage[0].path == str(tmp_path / "bob")
    assert usage[0].used_bytes == 500
    assert usage[0].percent_of_disk == 50.0
    assert usage[1].percent_of_disk == 25.0


def test_home_usage_returns_empty_when_home_path_is_missing(tmp_path) -> None:
    assert system.get_home_usage(tmp_path / "missing") == []


def test_disk_summaries_default_includes_home_and_data(monkeypatch) -> None:
    seen_paths: list[str] = []

    monkeypatch.setattr(system.Path, "exists", lambda self: True)

    def fake_get_disk_summary(path: str):
        seen_paths.append(path)
        return system.DiskSummary(
            path=path,
            total_bytes=1,
            used_bytes=1,
            free_bytes=0,
            percent=100.0,
        )

    monkeypatch.setattr(system, "_get_disk_summary", fake_get_disk_summary)

    disks = system.get_disk_summaries()

    assert seen_paths == ["/home", "/data"]
    assert [disk.path for disk in disks] == ["/home", "/data"]


def test_gpu_summary_parses_nvidia_smi_output(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            stdout=(
                "0, NVIDIA RTX 5880 Ada Generation, 84, 18075, 49140, 78, 266.92, 285.00\n"
                "1, NVIDIA RTX 5880 Ada Generation, N/A, 0, 49140, N/A, N/A, 285.00\n"
            )
        )

    monkeypatch.setattr(system.subprocess, "run", fake_run)

    gpus = system.get_gpu_summaries()

    assert len(gpus) == 2
    assert gpus[0].index == 0
    assert gpus[0].name == "NVIDIA RTX 5880 Ada Generation"
    assert gpus[0].utilization_percent == 84
    assert gpus[0].memory_used_bytes == 18075 * 1024 * 1024
    assert gpus[0].memory_total_bytes == 49140 * 1024 * 1024
    assert gpus[0].memory_percent == 36.8
    assert gpus[0].temperature_c == 78
    assert gpus[0].power_draw_watts == 266.92
    assert gpus[0].power_limit_watts == 285.0
    assert gpus[1].utilization_percent is None
    assert gpus[1].temperature_c is None
    assert gpus[1].power_draw_watts is None


def test_gpu_summary_returns_empty_when_nvidia_smi_is_unavailable(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(system.subprocess, "run", fake_run)

    assert system.get_gpu_summaries() == []


def test_gpu_summary_returns_empty_when_nvidia_smi_fails(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd="nvidia-smi")

    monkeypatch.setattr(system.subprocess, "run", fake_run)

    assert system.get_gpu_summaries() == []


def test_gpu_processes_parse_pmon_and_process_identity(monkeypatch) -> None:
    pmon_output = (
        "    0       2958     G      -      -      -      -      -      -      4      0    Xorg\n"
        "    0    4007844     C     88     86      -      -      -      -  18052      0    python\n"
        "    3     770589     C     63     51      -      -      -      -   8196      0    python\n"
    )

    def fake_query(args, timeout=2):
        assert args == ["pmon", "-c", "1", "-s", "um"]
        assert timeout == 3
        return pmon_output

    identities = {
        2958: {
            "user": "root",
            "process_name": "Xorg",
            "command": "/usr/lib/xorg/Xorg",
        },
        4007844: {
            "user": "zj",
            "process_name": "python",
            "command": "python run_dart.py",
        },
        770589: {
            "user": "wicsp",
            "process_name": "python",
            "command": ".venv/bin/python script.py",
        },
    }

    monkeypatch.setattr(system, "_run_nvidia_smi_query", fake_query)
    monkeypatch.setattr(system, "_lookup_process_identity", lambda pid, fallback: identities[pid])

    processes = system.get_gpu_processes()

    assert set(processes) == {0, 3}
    assert processes[0][0].pid == 4007844
    assert processes[0][0].user == "zj"
    assert processes[0][0].memory_used_bytes == 18052 * 1024 * 1024
    assert processes[0][0].sm_utilization_percent == 88
    assert processes[0][1].pid == 2958
    assert processes[0][1].user == "root"
    assert processes[0][1].memory_used_bytes == 4 * 1024 * 1024
    assert processes[0][1].sm_utilization_percent is None
    assert processes[3][0].user == "wicsp"


def test_gpu_summary_includes_process_and_user_usage(monkeypatch) -> None:
    gpu_output = (
        "0, NVIDIA RTX 5880 Ada Generation, 90, 20000, 50000, "
        "78, 260.00, 285.00\n"
    )
    pmon_output = (
        "    0       2958     G      -      -      -      -      -      -      4      0    Xorg\n"
        "    0    4007844     C     88     86      -      -      -      -  18052      0    python\n"
        "    0    4109064     C      7      5      -      -      -      -   1024      0    python\n"
    )

    def fake_query(args, timeout=2):
        if args[0].startswith("--query-gpu"):
            return gpu_output
        if args == ["pmon", "-c", "1", "-s", "um"]:
            return pmon_output
        raise AssertionError(args)

    identities = {
        2958: {
            "user": "root",
            "process_name": "Xorg",
            "command": "/usr/lib/xorg/Xorg",
        },
        4007844: {
            "user": "zj",
            "process_name": "python",
            "command": "python run_dart.py",
        },
        4109064: {
            "user": "wicsp",
            "process_name": "python",
            "command": ".venv/bin/python script.py",
        },
    }

    monkeypatch.setattr(system, "_run_nvidia_smi_query", fake_query)
    monkeypatch.setattr(system, "_lookup_process_identity", lambda pid, fallback: identities[pid])

    gpu = system.get_gpu_summaries()[0]
    user_usage = [
        (usage.user, usage.memory_percent, usage.sm_utilization_percent)
        for usage in gpu.users
    ]

    assert len(gpu.processes) == 3
    assert gpu.processes[0].user == "zj"
    assert gpu.processes[0].memory_percent == 36.1
    assert user_usage == [
        ("zj", 36.1, 88.0),
        ("wicsp", 2.0, 7.0),
        ("root", 0.0, None),
    ]
