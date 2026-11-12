# Power BI Executive Analytics Dashboard Kurulum Rehberi

Bu rehber, RetailPulse PostgreSQL Gold verisini Power BI Desktop'a bağlayıp yönetici panosunu kurar. M kodları Power Query **Advanced Editor**'a doğrudan yapıştırılabilir; sorgular projedeki gerçek Gold kolon adlarına göre yazılmıştır.

## 1. Bağlantı bilgileri ve şema notları

Power BI Desktop'ta **Get Data → PostgreSQL database** seçin:

| Alan | Değer |
| --- | --- |
| Server | `localhost:5434` |
| Database | `retailpulse` |
| Data connectivity mode | Import (önerilen) |

Repo'nun `.env.example` dosyasında veritabanı `retailpulse` olarak tanımlı. İstekteki `retailpulse_db` mevcut proje ayarıyla uyuşmuyor; Docker ortamınız gerçekten `retailpulse_db` kullanıyorsa aşağıdaki M örneklerindeki veritabanı adını değiştirin. Kullanıcı/parola için yerel `.env` dosyasındaki değerleri kullanın; parolayı PBIX dışında veya repoda yayımlamayın.

Power BI PostgreSQL bağlayıcısı/Npgsql sürücüsü istenirse Microsoft'un önerdiği sürümü kurup Power BI Desktop'ı yeniden başlatın. İlk bağlantıda **Database** kimlik doğrulamasını seçin. Import modu bu boyuttaki rapor için uygundur; DirectQuery seçerseniz her görsel etkileşimi PostgreSQL sorgusu çalıştırabilir.

### Gold şemasındaki gerçek adlar

- `gold.fact_orders` vardır. Ödeme kolonunun adı `payment_value` değil `total_payment`'tır; M sorgusu bu kolonu rapor ölçülerindeki `payment_value` adıyla sunar.
- Fiziksel `gold.mart_kpis` tablosu yoktur. `gold.mart_sales_daily` vardır, ancak onun `approved_revenue` alanı ürün tutarını toplar; aşağıdaki `gold_mart_kpis` sorgusu istenen toplam ödeme/AOV tanımlarıyla tutarlı olacak şekilde `fact_orders` üzerinden Power Query içinde sanal günlük KPI tablosu üretir.
- `gold.mart_customer_segments` vardır. Kolonları `customer_unique_id`, `recency`, `frequency`, `monetary`, `cluster_id`, `segment_name`, `updated_at`.
- Gold'da kalıcı churn tahmin tablosu yoktur. FastAPI `/api/v1/predict/churn` isteğe bağlı tahmin üretir; sonuçları raporda kullanmak için ayrıca bir tahmin tablosuna/dosyasına kaydetmek gerekir.
- Olist tutarları Brezilya Reali (BRL/R$) cinsindendir. Kur dönüşümü yapılmadıkça bunları USD (`$`) olarak etiketlemeyin. İş gereği USD etiketi zorunluysa önce kur dönüşümü uygulayın.

## 2. Power Query M sorguları

Her sorgu için **Home → Transform data → New Source → Blank Query → Advanced Editor** açın. Kodu yapıştırın, **Done** deyin ve sorguyu belirtilen adla yeniden adlandırın.

### 2.1 `gold_fact_orders`

Bu sorgu siparişleri müşteri eyaletiyle birleştirir; `total_payment` kolonunu `payment_value` olarak adlandırır. Sipariş başına tek satır kalır.

```powerquery
let
    Source = PostgreSQL.Database(
        "localhost:5434",
        "retailpulse",
        [Query = "
            SELECT
                f.order_id,
                f.customer_id,
                f.customer_unique_id,
                f.order_purchase_timestamp,
                f.order_purchase_timestamp::date AS order_date,
                f.order_approved_at,
                f.order_delivered_customer_date,
                f.order_estimated_delivery_date,
                f.order_status,
                f.total_product_amount,
                f.total_freight,
                f.total_payment AS payment_value,
                f.delivery_days,
                f.delivery_delay_days,
                COALESCE(c.customer_state, '(unknown)') AS customer_state
            FROM gold.fact_orders AS f
            LEFT JOIN gold.dim_customers AS c
                ON c.customer_unique_id = f.customer_unique_id
        "]
    ),
    Typed = Table.TransformColumnTypes(
        Source,
        {
            {"order_id", type text},
            {"customer_id", type text},
            {"customer_unique_id", type text},
            {"order_purchase_timestamp", type datetime},
            {"order_date", type date},
            {"order_approved_at", type datetime},
            {"order_delivered_customer_date", type datetime},
            {"order_estimated_delivery_date", type datetime},
            {"order_status", type text},
            {"total_product_amount", Currency.Type},
            {"total_freight", Currency.Type},
            {"payment_value", Currency.Type},
            {"delivery_days", type number},
            {"delivery_delay_days", type number},
            {"customer_state", type text}
        },
        "en-US"
    )
in
    Typed
```

`Currency.Type` sabit ondalık (4 basamak) veri tipidir; para simgesini ayrıca Model görünümünde biçimlendirin. Tarih alanı ilişki için `order_date`, saat bilgisi gereken analizler için `order_purchase_timestamp` olarak tutulur.

### 2.2 `gold_mart_kpis` (Power Query içinde sanal günlük mart)

Veritabanında `gold.mart_kpis` bulunmadığından, bu sorgu günlük KPI satırlarını `gold.fact_orders` üzerinden üretir. Sorgu adı Power BI modelinde `gold_mart_kpis` olsun. Kayıtlar tarih düzeyinde toplulaştırıldığı için eyalet/segment kesitleri için bu tabloyu değil, aşağıdaki `gold_fact_orders` ölçülerini kullanın.

```powerquery
let
    Source = PostgreSQL.Database(
        "localhost:5434",
        "retailpulse",
        [Query = "
            SELECT
                order_purchase_timestamp::date AS sales_date,
                COUNT(*)::bigint AS order_count,
                SUM(total_payment)::numeric(16,2) AS total_revenue,
                AVG(total_payment)::numeric(16,2) AS average_order_value,
                AVG(delivery_days)::numeric(12,4) AS average_delivery_days,
                COUNT(*) FILTER (WHERE delivery_delay_days > 0)::bigint AS delayed_order_count
            FROM gold.fact_orders
            GROUP BY order_purchase_timestamp::date
            ORDER BY sales_date
        "]
    ),
    Typed = Table.TransformColumnTypes(
        Source,
        {
            {"sales_date", type date},
            {"order_count", Int64.Type},
            {"total_revenue", Currency.Type},
            {"average_order_value", Currency.Type},
            {"average_delivery_days", type number},
            {"delayed_order_count", Int64.Type}
        },
        "en-US"
    )
in
    Typed
```

Eğer fiziksel `gold.mart_sales_daily` tablosunu içe almak isterseniz Advanced Editor'daki sorgu gövdesini aşağıdakiyle değiştirin; bu gerçek martın geliri `total_product_amount` üzerinden hesapladığını unutmayın:

```powerquery
let
    Source = PostgreSQL.Database("localhost:5434", "retailpulse"),
    SalesDaily = Source{[Schema = "gold", Item = "mart_sales_daily"]}[Data],
    Typed = Table.TransformColumnTypes(
        SalesDaily,
        {
            {"sales_date", type date},
            {"approved_revenue", Currency.Type},
            {"order_count", Int64.Type},
            {"average_order_value", Currency.Type}
        },
        "en-US"
    )
in
    Typed
```

### 2.3 `gold_mart_customer_segments`

```powerquery
let
    Source = PostgreSQL.Database("localhost:5434", "retailpulse"),
    Segments = Source{[Schema = "gold", Item = "mart_customer_segments"]}[Data],
    Typed = Table.TransformColumnTypes(
        Segments,
        {
            {"customer_unique_id", type text},
            {"recency", Int64.Type},
            {"frequency", Int64.Type},
            {"monetary", Currency.Type},
            {"cluster_id", Int64.Type},
            {"segment_name", type text},
            {"updated_at", type datetimezone}
        },
        "en-US"
    )
in
    Typed
```

### 2.4 Boyut tablosu `dim_customer`

Segment filtresinin sipariş görsellerine müşteri bazında yayılması için bu tabloyu da içe alın.

```powerquery
let
    Source = PostgreSQL.Database("localhost:5434", "retailpulse"),
    Customers = Source{[Schema = "gold", Item = "dim_customers"]}[Data],
    Typed = Table.TransformColumnTypes(
        Customers,
        {
            {"customer_unique_id", type text},
            {"customer_city", type text},
            {"customer_state", type text},
            {"customer_zip_code_prefix", type text}
        },
        "en-US"
    )
in
    Typed
```

## 3. Yıldız şema ilişkileri

Model görünümünde ilişki uçlarını şu şekilde kurun. Filtre akışını mümkün olduğunca boyuttan fact'e tek yönlü tutun.

| Bir taraf (1) | Çok tarafı (*) | Cardinality | Cross-filter |
| --- | --- | --- | --- |
| `dim_customer[customer_unique_id]` | `gold_fact_orders[customer_unique_id]` | 1:* | Single, `dim_customer` → `gold_fact_orders` |
| `dim_customer[customer_unique_id]` | `gold_mart_customer_segments[customer_unique_id]` | 1:1 | Both (segment slicer'ının müşteri ve sipariş fact'ine ulaşması için bu ilişkiye özel) |
| `dim_date[Date]` | `gold_fact_orders[order_date]` | 1:* | Single, `dim_date` → `gold_fact_orders` |
| `dim_date[Date]` | `gold_mart_kpis[sales_date]` | 1:* | Single, `dim_date` → `gold_mart_kpis` |

`dim_customer` ve `gold_mart_customer_segments` müşteri başına tek satır içerir; müşteri boyutunun anahtarı benzersiz olmalıdır. Segment ilişkisini **Both** yapmak Power BI'da uyarı çıkarırsa iki yönlü ilişkiyi yalnızca bu müşteri-segment kenarında etkinleştirin ve Model görünümünde başka alternatif filtre yolları olmadığını doğrulayın. Alternatif olarak segment slicer'ını sadece segment görsellerine uygulayın ve sipariş görselleri için görsel etkileşimlerini kapatın.

### Takvim tablosu

**Modeling → New table** ile aşağıdaki DAX'ı oluşturun, sonra `dim_date[Date]` kolonunu **Mark as date table** olarak işaretleyin:

```DAX
dim_date =
ADDCOLUMNS(
    CALENDAR(
        MIN(gold_fact_orders[order_date]),
        MAX(gold_fact_orders[order_date])
    ),
    "Year", YEAR([Date]),
    "MonthNo", MONTH([Date]),
    "Month", FORMAT([Date], "MMM"),
    "YearMonth", FORMAT([Date], "yyyy-MM"),
    "YearMonthSort", YEAR([Date]) * 100 + MONTH([Date])
)
```

`dim_date[YearMonth]` için **Sort by column → YearMonthSort** ayarlayın. Tarih aralığı slicer'ında `dim_date[Date]` kullanın. `gold_mart_kpis` günlük olduğundan takvimle doğrudan tarihten bağlanır.

## 4. DAX ölçüleri

Power BI'da **Modeling → New measure** seçip her formülü ayrı ölçü olarak ekleyin. İsimler Türkçe olduğu için köşeli parantez içindeki adları aynen kullanabilirsiniz.

```DAX
Toplam Sipariş =
COUNTROWS(gold_fact_orders)
```

```DAX
Toplam Ciro =
SUM(gold_fact_orders[payment_value])
```

```DAX
Ortalama Sipariş Değeri (AOV) =
DIVIDE([Toplam Ciro], [Toplam Sipariş], 0)
```

```DAX
Ortalama Teslimat Süresi (Gün) =
AVERAGE(gold_fact_orders[delivery_days])
```

```DAX
Gecikme Oranı (%) =
DIVIDE(
    CALCULATE(
        COUNTROWS(gold_fact_orders),
        gold_fact_orders[delivery_delay_days] > 0
    ),
    [Toplam Sipariş],
    0
)
```

İstenen formül tüm siparişleri payda alır. Yalnızca teslim edilmiş ve tahmini teslim tarihi bulunan siparişlerde gecikme oranı istenirse payda için ayrıca `delivery_delay_days` boş olmayan kayıtları sayan bir ölçü kullanın.

```DAX
Churn Risk Oranı (%) =
VAR RiskliMusteriler =
    CALCULATE(
        DISTINCTCOUNT(gold_mart_customer_segments[customer_unique_id]),
        REMOVEFILTERS(gold_mart_customer_segments[segment_name]),
        gold_mart_customer_segments[segment_name]
            IN {"At Risk", "Hibernating/Lost"}
    )
VAR TumSegmentliMusteriler =
    CALCULATE(
        DISTINCTCOUNT(gold_mart_customer_segments[customer_unique_id]),
        REMOVEFILTERS(gold_mart_customer_segments[segment_name])
    )
RETURN
    DIVIDE(RiskliMusteriler, TumSegmentliMusteriler, 0)
```

Bu ölçü, mevcut K-Means tablolarında **At Risk** ve **Hibernating/Lost** segmentlerini riskli kabul eder. Kalıcı churn tahmin tablosu eklendiğinde, örneğin `gold_churn_predictions` (`customer_unique_id`, `churn_probability`) için model skoru tabanlı oranı ayrıca ekleyin:

```DAX
Tahmin Edilen Churn Oranı (%) =
VAR TahminliMusteriler =
    DISTINCTCOUNT(gold_churn_predictions[customer_unique_id])
VAR ChurnRiskliMusteriler =
    CALCULATE(
        DISTINCTCOUNT(gold_churn_predictions[customer_unique_id]),
        gold_churn_predictions[churn_probability] >= 0.50
    )
RETURN
    DIVIDE(ChurnRiskliMusteriler, TahminliMusteriler, 0)
```

Bu son ölçü tablo oluşturulana ve `dim_customer` ile ilişkilendirilene kadar çalışmaz. API çağrılarının mevcut sonucu kendiliğinden Gold'a kaydedilmediğinden, bu tabloyu ETL/çıkarım işinde doldurmanız gerekir.

### Ölçü biçimleri

- `Toplam Ciro`, `Ortalama Sipariş Değeri (AOV)`: **Fixed decimal number / Currency**. Olist verisini olduğu gibi göstermek için biçim `$` değil `R$ #,##0.00`; USD gerekiyorsa önce kur çevrimi ekleyin.
- `Ortalama Teslimat Süresi (Gün)`: Decimal number, 1–2 basamak.
- `Gecikme Oranı (%)`, `Churn Risk Oranı (%)`, `Tahmin Edilen Churn Oranı (%)`: Percentage, 1 basamak.
- Sipariş ve müşteri sayıları: Whole number, binlik ayırıcı açık.

## 5. Dashboard tuvali ve görsel yerleşimi

**Format page → Canvas settings → 16:9** seçin. 1366×768 veya 1280×720 çözünürlük hedefleyin; üstten alta görsel hiyerarşisi kurun.

### Üst sıra: KPI kartları

Sayfanın üst bölümüne eşit genişlikte dört Card görseli yerleştirin:

1. **AOV** → `[Ortalama Sipariş Değeri (AOV)]`, `R$` para biçimi.
2. **Toplam Ciro** → `[Toplam Ciro]`, `R$` para biçimi.
3. **Ort. Teslimat Süresi** → `[Ortalama Teslimat Süresi (Gün)]`, gün.
4. **Gecikme Oranı** → `[Gecikme Oranı (%)]`, yüzde.

Başlıkları kısa tutun; kart alt etiketlerinde seçili dönem bilgisini gösterin.

### Orta sıra: zaman ve segment

- **Aylık Sipariş Hacmi & Ciro Trendi**: Line and clustered column chart. X-axis `dim_date[YearMonth]`; Column y-axis `[Toplam Sipariş]`; Line y-axis `[Toplam Ciro]`. `YearMonth` alanını `YearMonthSort` ile sıralayın. Tutar ve adet farklı ölçeklerde olduğu için çizgi serisi için secondary axis kullanın.
- **Müşteri Segmentleri Dağılımı**: Treemap veya Donut. Group/Legend `gold_mart_customer_segments[segment_name]`; Values `DISTINCTCOUNT(gold_mart_customer_segments[customer_unique_id])`. Tooltip'e ortalama `recency`, `frequency`, `monetary` eklenebilir. İstenirse `[Churn Risk Oranı (%)]` ayrıca KPI kartı olarak eklenebilir.

### Alt sıra: eyalet bazlı teslimat

- **Eyalet Bazlı Teslimat Gecikmeleri**: Bar chart. Y-axis `gold_fact_orders[customer_state]`; X-axis `[Gecikme Oranı (%)]` veya `AVERAGE(gold_fact_orders[delivery_delay_days])`. İlk ölçü gecikmeli sipariş oranı, ikinci ölçü gecikme gün ortalamasıdır. Eyalet adlarını artan/azalan değere göre sıralayın ve `(unknown)` kategorisini gerektiğinde filtreleyin.

### Slicers ve etkileşimler

Sol kenar veya üst bölümde yatay/kompakt slicer'lar kullanın:

- **Tarih aralığı** → `dim_date[Date]`, Between.
- **Eyalet** → `gold_fact_orders[customer_state]` veya `dim_customer[customer_state]`, dropdown ve arama açık.
- **Müşteri Segmenti** → `gold_mart_customer_segments[segment_name]`, dropdown.

**Format → Edit interactions** ile tarih ve eyalet slicer'larının kartları, trendi, segment ve eyalet grafiğini filtrelediğini doğrulayın. Segment slicer'ı sipariş temelli görselleri filtrelemiyorsa 3. bölümdeki müşteri-segment iki yönlü ilişkiyi kontrol edin veya segment slicer etkileşimini yalnızca segment/KPI görsellerine uygulayın.

## 6. Son kontrol listesi

- Power Query'de `gold_fact_orders`, `gold_mart_kpis`, `gold_mart_customer_segments` ve `dim_customer` hatasız yenileniyor.
- `gold_fact_orders[order_id]` sipariş başına tekil; müşteri boyut anahtarı tekil.
- Tarih kolonları Date/DateTime; para kolonları Fixed decimal; sayımlar tam sayı; gecikme metrikleri decimal.
- Date ve customer ilişkileri 1:*; ilişki yönleri slicer davranışıyla doğrulandı.
- AOV boş/0 sipariş durumunda hata vermiyor (`DIVIDE` varsayılan 0 kullanıyor).
- Para kartlarında BRL/R$ gösteriliyor veya USD'ye dönüştürme açıkça uygulanıyor.
- Tarih, eyalet ve segment slicer'ları her görsel için **Edit interactions** ile kontrol edildi.
- Rapor yenilemesinden sonra **File → Save** ile `.pbix` kaydedildi.
