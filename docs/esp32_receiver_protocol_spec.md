# ESP32 受信プロトコル仕様

このドキュメントは、`gt7_seat_esp` の ESP32 受信処理を、別システムから互換実装できるようにコード準拠で整理したものです。

対象は「PC/外部システム -> ESP32」の受信仕様です。あわせて、ハンドシェイクで ESP32 から返るフレームも記載します。

## 1. 通信条件

- 物理層: UART シリアル
- ボーレート: `115200`
- プロトコルバージョン: `1`
- マジック: ASCII `"G7"` (`0x47 0x37`)
- エンディアン: **little-endian**
- ESP32 側最大ペイロード長: `96` bytes
- ESP32 側最大フレーム長: `128` bytes

## 2. フレーム共通フォーマット

全フレームは 12 byte ヘッダ + 可変長ペイロードです。

| Offset | Size | Type | Name | 内容 |
| --- | ---: | --- | --- | --- |
| 0 | 2 | `char[2]` | `magic` | 固定値 `"G7"` |
| 2 | 1 | `uint8` | `version` | 固定値 `1` |
| 3 | 1 | `uint8` | `frame_type` | `FrameType` |
| 4 | 1 | `uint8` | `flags` | 現状未使用。`0` 推奨 |
| 5 | 1 | `uint8` | `reserved` | 現状未使用。`0` 固定 |
| 6 | 2 | `uint16` | `seq` | 送信側シーケンス番号 |
| 8 | 2 | `uint16` | `device_id` | 対象 ESP32 ID |
| 10 | 2 | `uint16` | `payload_len` | ペイロード長 |
| 12 | n | `bytes` | `payload` | `payload_len` 分 |

### 実装上の注意

- `payload_len > 96` のフレームは ESP32 側で破棄されます。
- `version != 1` のフレームは ESP32 側で破棄されます。
- チェックサムや CRC はありません。
- `seq` は ESP32 側では**受信時に未使用**です。重複排除や順序保証は行いません。
- `device_id` も受信時にはほぼ未検証です。`Telemetry` / `Event` / `SectionPreview` は `device_id` 不一致でも処理されます。

## 3. FrameType 一覧

| 値 | 名前 | 主方向 | ESP32 での扱い |
| ---: | --- | --- | --- |
| 1 | `PING` | 双方向 | 受信すると `PONG` を返す |
| 2 | `PONG` | 双方向 | 受信するとリンク生存確認だけ更新 |
| 3 | `TELEMETRY` | 外部 -> ESP32 | テレメトリ状態を更新 |
| 4 | `BIND` | 外部 -> ESP32 | PS5 IP を保存し `ACK` を返す |
| 5 | `EVENT` | 外部 -> ESP32 | 単発イベントを実行 |
| 6 | `ACK` | ESP32 -> 外部 | ESP32 側では受信しても未処理 |
| 7 | `SECTION_PREVIEW` | 外部 -> ESP32 | LED 範囲プレビューを実行 |

## 4. 各 FrameType の仕様

### 4.1 `PING` (`1`)

- ペイロード長: `0`
- 方向:
  - ESP32 -> 外部: 定期送信あり
  - 外部 -> ESP32: 受信可

#### 外部 -> ESP32

- ESP32 はリンク生存時刻を更新します。
- その後、`PONG` を返信します。
- 返信 `PONG` の `device_id` には、**受信した `PING` ヘッダの `device_id` がそのまま使われます。**

#### ESP32 -> 外部

- 起動直後に 1 回送信。
- その後は約 `1000ms` ごとに送信。
- `device_id` には ESP32 ビルド時定数 `GT7_DEVICE_ID` が入ります。

### 4.2 `PONG` (`2`)

- ペイロード長: `0`
- 方向: 双方向

#### 外部 -> ESP32

- ESP32 はリンク生存時刻を更新するだけです。
- それ以外の副作用はありません。

### 4.3 `TELEMETRY` (`3`)

- ペイロード長: **24 bytes 必須**
- 方向: 外部 -> ESP32

24 bytes 未満の場合、ESP32 はフレームを無視します。
25 bytes 以上でも先頭 24 bytes だけが意味を持ち、余剰分は無視されます。

#### ペイロードレイアウト

| Offset | Size | Type | Name | 備考 |
| --- | ---: | --- | --- | --- |
| 0 | 4 | `float32` | `car_speed` | m/s |
| 4 | 4 | `float32` | `engine_rpm` | エンジン回転数 |
| 8 | 4 | `float32` | `rpm_alert_min` | シフト点下限目安 |
| 12 | 4 | `float32` | `rpm_alert_max` | シフト点上限目安 |
| 16 | 1 | `uint8` | `throttle` | `0..255` |
| 17 | 1 | `uint8` | `brake` | `0..255` |
| 18 | 1 | `int8` | `current_gear` | `-1`=ニュートラル想定、`0`=リバース |
| 19 | 4 | `float32` | `velocity_right` | 車体ローカル右方向速度。右が正、左が負 |
| 23 | 1 | `uint8` | `play_state` | `1` のときだけ `PlayRace` 扱い、それ以外は `PlayIdle` |

#### ESP32 側の反応

- `last_pc_seen_ms_` と `last_telemetry_rx_ms_` を更新します。
- テレメトリ状態を上書きします。
- 直後にアクチュエータ更新を行います。

#### 実際の利用先

- `car_speed`: ファン出力と速度系 LED 演出に使用
- `engine_rpm`, `rpm_alert_min`, `rpm_alert_max`: RPM 演出に使用
- `throttle`: 右アーム LED ゲージに使用
- `brake`: 左アーム LED ゲージに使用
- `current_gear`: ギア別色・ギア発光演出に使用
- `velocity_right`: 横 G 代替として振動トリガーに使用
- `play_state`: `Race` / `Idle` / `Sleep` 切替判定に使用

#### 重要な注意

- 現行の Python 実装では `play_state` は常に `0` を送るため、**別システムで本当にレース演出を出したい場合は `1` を送る必要があります。**
- `velocity_right` の絶対値が `15.0` を超えると、レース中は振動出力が ON になります。

### 4.4 `BIND` (`4`)

- ペイロード長: 通常 `4 bytes`
- 方向: 外部 -> ESP32

#### ペイロードレイアウト

| Offset | Size | Type | Name | 備考 |
| --- | ---: | --- | --- | --- |
| 0 | 4 | `uint8[4]` | `ps5_ip` | IPv4 アドレス 4 octet |

#### ESP32 側の反応

- `payload_len >= 4` の場合:
  - 先頭 4 byte を IPv4 として保存
  - `has_binding_ = true`
  - 同じ IP を payload に載せた `ACK` を返信
- `payload_len < 4` の場合:
  - バインド解除
  - `has_binding_ = false`
  - 空 payload の `ACK` を返信

#### 重要な注意

- 5 byte 以上送っても、実際に使うのは**先頭 4 byte のみ**です。
- 現行 ESP32 実装では、保存した `bound_ps5_ip_` / `has_binding_` は**演出処理の条件分岐には未使用**です。  
  つまり、`BIND` しなくても `TELEMETRY` や `EVENT` は受け取ればそのまま処理されます。

### 4.5 `EVENT` (`5`)

- ペイロード長: **2 bytes 必須**
- 方向: 外部 -> ESP32

2 bytes 未満の場合、ESP32 はフレームを無視します。

#### ペイロードレイアウト

| Offset | Size | Type | Name | 備考 |
| --- | ---: | --- | --- | --- |
| 0 | 1 | `uint8` | `event_id` | イベント種別 |
| 1 | 1 | `uint8` | `event_value` | 強度や種別補助値 |

#### `event_id` 定義

| 値 | 名前 | ESP32 の反応 |
| ---: | --- | --- |
| 1 | `EventCollision` | 衝突演出を開始 |
| 2 | `EventLap` | ラップ演出を開始 |

#### `EventCollision` (`event_id = 1`)

- `event_value` は衝突強度として扱われます。
- 振動時間は以下のように決まります。
  - `0` のとき: `800ms`
  - `1..255` のとき: 約 `200ms .. 800ms` に線形スケール
- さらに LED 側では約 `900ms` の赤点滅演出が走ります。

#### `EventLap` (`event_id = 2`)

- `event_value` は**現状未使用**です。
- 受信すると約 `600ms` の白フラッシュ演出が走ります。

#### その他の `event_id`

- 未知の `event_id` は無視されます。

### 4.6 `ACK` (`6`)

- ペイロード長:
  - `0` または
  - `4` (`BIND` 成功時の IPv4)
- 主方向: ESP32 -> 外部

#### 用途

- `BIND` 受信に対する応答専用です。

#### ペイロードレイアウト

| 条件 | 内容 |
| --- | --- |
| バインド成功 | `uint8[4]` の IPv4 |
| バインド解除 / 不正 payload | 空 payload |

#### 外部 -> ESP32

- 送っても ESP32 側では何もしません。

### 4.7 `SECTION_PREVIEW` (`7`)

- ペイロード長: **5 bytes 必須**
- 方向: 外部 -> ESP32

5 bytes 未満の場合、ESP32 はフレームを無視します。

#### ペイロードレイアウト

| Offset | Size | Type | Name | 備考 |
| --- | ---: | --- | --- | --- |
| 0 | 1 | `uint8` | `strip_id` | `0`=Base, `1`=Monitor |
| 1 | 2 | `uint16` | `start_index` | little-endian |
| 3 | 2 | `uint16` | `end_index` | little-endian |

#### ESP32 側の反応

- 約 `10秒` のプレビュー表示を開始します。
- プレビュー中は通常アニメーションより優先されます。
- 指定範囲を LED で可視化します。

#### `strip_id` の扱い

| 値 | 扱い |
| ---: | --- |
| 0 | Base ストリップ |
| 1 | Monitor ストリップ |
| その他 | **Base 扱い** |

#### インデックスの扱い

- `start_index` / `end_index` は対象ストリップ LED 数にクランプされます。
- 範囲は**両端を含む inclusive** です。
- `start_index > end_index` でも可。内部で小さい方から大きい方まで塗ります。
- 単点指定 (`start == end`) も可です。

## 5. ESP32 側のリンク状態判定

別システムが ESP32 を安定動作させる際に重要なタイムアウトです。

- `PING` / `PONG` / `BIND` / `EVENT` / `SECTION_PREVIEW` / `TELEMETRY` のどれかを受けると PC 生存時刻が更新されます
- `TELEMETRY` を最後に受けてから `2500ms` 超で、テレメトリは stale 扱いになります
- PC 生存時刻と最新テレメトリの両方が `2500ms` を超えると、リンク不健康扱いになります
- ESP32 自身は `1000ms` ごとに `PING` を送ります

### 実運用の推奨

- `PONG` だけ返す最小実装でもリンク維持は可能です
- ただし演出用には `TELEMETRY` を少なくとも数百 ms 以内に継続送信するのが前提です
- 現行 PC 実装の送信上限は `20Hz` です

## 6. 受信実装を別システムで作るときの注意点

1. `HEADER` は little-endian です。`uint16` を big-endian で送ると解釈されません。
2. `flags` と `reserved` は現状未使用なので `0` を送ってください。
3. `seq` は任意ですが、デバッグしやすさのため単調増加推奨です。
4. `device_id` は厳密検証されていませんが、将来互換を考えると対象 ESP32 の `GT7_DEVICE_ID` を入れるのが安全です。
5. `BIND` は現状ほぼメタデータですが、外部システムが既存 PC 実装と共存するなら送っておく方が無難です。
6. `TELEMETRY.play_state` は `1` を送らない限り Race 演出になりません。
7. `SECTION_PREVIEW` は通常演出を 10 秒間上書きするため、本番運用では常用しない方が安全です。
8. シリアル破損時の再同期は `"G7"` マジック頼みです。ペイロードに偶然 `"G7"` が含まれても通常は問題ありませんが、破損復旧は完全ではありません。
9. ESP32 側には ACK 再送制御がありません。必要なら送信側でタイムアウト・再送方針を持ってください。

## 7. 送信例

### `EVENT` 送信例

- `frame_type = 5`
- `device_id = 1`
- `payload = [1, 128]`

意味:

- `event_id = 1` (`EventCollision`)
- `event_value = 128`

### `SECTION_PREVIEW` 送信例

- `frame_type = 7`
- `device_id = 1`
- `payload = [1, 10, 0, 40, 0]`

意味:

- `strip_id = 1` (`Monitor`)
- `start_index = 10`
- `end_index = 40`

### `TELEMETRY` 送信時の struct

Python 互換のパック形式:

```python
struct.pack("<ffffBBbfB",
    car_speed,
    engine_rpm,
    rpm_alert_min,
    rpm_alert_max,
    throttle,
    brake,
    current_gear,
    velocity_right,
    play_state,
)
```
