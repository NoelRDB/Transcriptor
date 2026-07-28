from transcriptor_engine import hardware


def test_hardware_inventory_reports_capacity_and_cuda(monkeypatch):
    monkeypatch.setattr(hardware, "_cpu_name", lambda: "CPU de prueba")
    monkeypatch.setattr(
        hardware,
        "_nvidia_snapshot",
        lambda: {
            "name": "GPU de prueba",
            "totalVramMiB": 8192,
            "usedVramMiB": 1024,
            "utilizationPercent": 25,
            "driverVersion": "1.0",
        },
    )
    monkeypatch.setattr(hardware.psutil, "cpu_count", lambda logical=True: 16 if logical else 8)

    result = hardware.get_hardware_info(cuda_available=True)

    assert result["cpu"]["name"] == "CPU de prueba"
    assert result["cpu"]["physicalCores"] == 8
    assert result["cpu"]["logicalCores"] == 16
    assert result["gpu"]["totalVramMiB"] == 8192
    assert result["cudaAvailable"] is True
    assert result["recommendedProfile"] == "maximum"
