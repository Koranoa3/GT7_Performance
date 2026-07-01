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

ESP への送信を使う場合は、シリアルポートと手動紐づけを追加できます。

```bash
python main.py 192.168.0.10 --esp-port COM3 --bind 192.168.0.10:1
```

- `--esp-port` を省略すると、接続可能なシリアルポートを自動探索します
- `--bind` は `PS5_IP:ESP_ID` 形式です
- ESP 側は `PING` を送って自分の `ESP_ID` を知らせ、PC 側は `PONG` と `BIND` を返します
- 連続データは 20Hz 上限で送信されます

リポジトリ直下の `config.ini` も起動時に読み込みます。現在は `FAN_SPEED_MULTIPLIER` に加えて、PC 内部の `car_speed` を m/s 単位で上限制限する `MAX_CAR_SPEED` も設定できます。

## 構成

- `main.py`: 起動用の薄いエントリポイント
- `gt7_runtime.py`: CLI、実行ループ、出力先解決
- `gt7_writer.py`: CSV 書き込み処理
- `gt7_formatting.py`: Telemetry を CSV 行へ整形する処理
- `gt7_config.py`: 列定義と数値フォーマット設定
- `gt7_protocol.py`: PC/ESP 共通のバイナリフレーム定義
- `gt7_esp_bridge.py`: ESP とのシリアル接続、識別、紐づけ、20Hz 送信制御

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
