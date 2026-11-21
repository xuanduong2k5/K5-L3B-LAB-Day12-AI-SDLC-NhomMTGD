# Ma trận truy vết Phase 1

| AC | Cách kiểm chứng | Bằng chứng | Kết quả |
|---|---|---|---|
| Headless gather/quán | Chạy unittest và headless bằng seed cố định | Kết quả terminal của `python3 -m unittest` | đạt |
| Kho qua gather sang quan | Smoke test inventory | `tests/test_smoke_p1.py::Integration` | đạt |
| TEAM khớp contract | Chạy tools/check_team.py | TEAM.md + game.contract.json | đạt |

## Đánh giá ngắn
- Yêu cầu nào đạt / chưa đạt:
- Điều cần chỉnh cho phase sau:
