# forza_hub_pc

Forza Horizon の Data Out UDP テレメトリを受信し、`gt7_seat_esp` が受け付ける ESP32 シリアルプロトコルへ変換して送る Go 製 CLI です。

## 役割

- `0.0.0.0` で Forza テレメトリを受信
- 324 byte パケットをフル分解
- ESP32 の自動探索、`PING` / `PONG` / `BIND` / `ACK` を用いた接続維持
- ESP 向け `TELEMETRY` / `EVENT` 送信
- CLI 上で Forza 受信状況と ESP 接続状況を行書き換え表示

## ビルド

```powershell
cd forza_hub_pc
go build .
```

## 実行例

```powershell
go run . -listen 0.0.0.0:12350
```

固定 COM ポートを使う場合:

```powershell
go run . -listen 0.0.0.0:12350 -esp-port COM4
```

## 主なフラグ

- `-listen`
  - Forza Data Out を受ける UDP アドレス
- `-esp-port`
  - 固定 COM ポート。未指定なら `COM1..scan-max-com` を探索
- `-scan-max-com`
  - 自動探索する最大 COM 番号
- `-telemetry-rate`
  - ESP への通常テレメトリ送信上限 Hz
- `-idle-rate`
  - Forza 停止中に `play_state=0` を送る周期 Hz
- `-collision-threshold`
  - 衝突イベント発火の加速度閾値
- `-collision-ceiling`
  - 衝突強度を 255 に丸める加速度
- `-bind-ip`
  - `BIND` に入れる IPv4 を固定指定。未指定なら Forza 送信元 IP、未受信なら `127.0.0.1`
- `-zero-gear-neutral`
  - `Gear=0` を ESP のニュートラル `-1` に変換するか

## 実装メモ

- `play_state` は `IsRaceOn` ではなく「直近でテレメトリを受けているか」で決めています。
- Forza が送信を止めたら、ESP を素早く `Idle` に戻すために合成したアイドルテレメトリを送ります。
- 衝突イベントは `AccelerationX/Y/Z` の絶対値最大で判定します。
