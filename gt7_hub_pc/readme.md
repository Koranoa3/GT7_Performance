環境：Python 3.8.10

# GT7 Hub PC

PS5 の Gran Turismo 7 テレメトリを受信して、CSV に記録する PC 側の起点です。

## セットアップ

1. Python 3.8.10 をインストールする
2. 仮想環境を作成する
   ```bash
   python3.8 -m venv .venv
   ```
3. 仮想環境をアクティベートする
   ```bash
   .venv\Scripts\activate
   ```
4. 依存関係をインストールする
   ```bash
   pip install -r requirements.txt
   ```

## 起動

PS5 の IP アドレスを直接指定する場合:
```bash
python main.py 192.168.0.10
```

起動後に IP アドレスを入力する場合:
```bash
python main.py
```

CSV は既定で `records/gt7_telemetry_YYYYMMDD_HHMMSS.csv` に保存されます。

## 記録列

- `logged_at`
- `packet_id`
- `received_time`
- `car_speed`
- `velocity_x`, `velocity_y`, `velocity_z`
- `angular_velocity_x`, `angular_velocity_y`, `angular_velocity_z`
- `engine_rpm`
- `rpm_alert_min`, `rpm_alert_max`
- `throttle`, `brake`
- `turbo_boost`
- `current_gear`
- `in_race`
- `cars_in_race`
- `lap_count`
- `laps_in_race`
- `best_lap_time`
- `last_lap_time`
