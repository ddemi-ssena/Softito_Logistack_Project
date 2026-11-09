# RetailPulse — AI Coding Agent Project Brief

> **Amaç:** Bu doküman, RetailPulse projesini Claude Code, Cursor Agent veya benzeri bir kodlama ajanına devretmek için ana proje tanımıdır. Ajan bu dosyayı okuyarak kapsamı, mimariyi, teslim ölçütlerini ve çalışma kurallarını anlayabilmelidir.

## 1. Proje Özeti

**Proje adı:** RetailPulse  
**Tam ad:** Real-Time E-Commerce Analytics & Business Intelligence Platform  
**Proje türü:** Bireysel bitirme projesi  
**Öncelikli odak:** Veri analitiği + Data Engineering  
**Hedef süre:** Yaklaşık 7 gün  
**Teslim:** Çalışan uygulama, GitHub deposu, teknik dokümantasyon ve sunum.

RetailPulse, Olist e-ticaret veri setini kullanarak tarihsel sipariş verilerini analitik bir veri katmanına dönüştüren; ayrıca geçmiş sipariş kayıtlarından kontrollü biçimde olay akışı simüle ederek Kafka producer-consumer mimarisini gösteren uçtan uca bir analitik platformdur.

Platform şu iş sorularını yanıtlamalıdır:
- Satışlar zaman içinde nasıl değişiyor?
- Hangi ürün kategorileri daha fazla gelir getiriyor?
- Müşteri segmentleri nasıl dağılıyor?
- Teslimat performansı ve gecikmeler nasıl?
- Günlük satış miktarı için kısa vadeli tahmin üretilebilir mi?
- Kafka üzerinden gelen sipariş olayları sistemde nasıl izlenebilir?

**Önemli doğruluk notu:** Olist veri seti tarihsel (2016–2018) veridir. Kafka akışı gerçek canlı e-ticaret trafiği değildir; tarihsel kayıtların kontrollü hızda yeniden yayınlanmasıyla oluşturulan bir simülasyondur. Arayüz ve sunum bunu açıkça belirtmelidir.

---

## 2. Kullanılacak Teknoloji Yığını

| Katman | Teknoloji | Kullanım Amacı |
| :--- | :--- | :--- |
| **Programlama** | Python 3.11 | ETL, producer, consumer, API, analiz |
| **Veri işleme** | Pandas, NumPy | Temizleme, dönüştürme, özellik üretimi |
| **Veritabanı** | PostgreSQL 16 | Ham, temizlenmiş ve analitik veriler |
| **Event streaming** | Apache Kafka (KRaft) / Redpanda | Sipariş olaylarını aktarma |
| **API** | FastAPI | Analitik sonuçları servis etme (Opsiyonel/B planı mevcuttur) |
| **Dashboard** | Streamlit | Etkileşimli analitik arayüz |
| **Grafik** | Plotly | Grafik ve görselleştirme |
| **ML** | Scikit-learn | K-Means, Random Forest ve metrikler (P1 öncelikli) |
| **Container** | Docker, Docker Compose | Servisleri birlikte çalıştırma |
| **Test** | Pytest | ETL, API ve veri doğrulama testleri |
| **Versiyon kontrolü**| Git, GitHub | Kaynak kod yönetimi |

### Kapsam dışı / İlk sürümde kullanılmayacaklar
- Apache Spark
- Apache Airflow
- Kubernetes
- Ayrı bir React/Vue frontend
- Mikroservis mimarisi
- Gerçek bir ödeme sistemi veya canlı e-ticaret entegrasyonu

---

## 3. Veri Kaynağı

**Olist Brazilian E-Commerce Public Dataset**  
Kaynak: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

Veri seti yaklaşık 100 bin sipariş ve birden fazla ilişkili CSV tablosu içerir.

### MVP'de kullanılacak dosyalar
- `olist_orders_dataset.csv`
- `olist_customers_dataset.csv`
- `olist_order_items_dataset.csv`
- `olist_products_dataset.csv`
- `olist_order_payments_dataset.csv`
- `olist_order_reviews_dataset.csv`

İhtiyaç olursa:
- `olist_sellers_dataset.csv`
- `product_category_name_translation.csv`

*(İlk sürümde geolocation tablosunu kullanmak zorunlu değildir.)*

### Kritik Veri Kuralları ve Filtreler

1. **Tarih Aralığı Filtresi (Data Skew Engelleme):** Olist veri setinde 2016 sonu ve 2018 sonu verileri seyrektir. Zaman serisi, trend ve RFM analizlerinde veri bütünlüğünü korumak adına varsayılan analitik aralık olarak **2017-01-01 ile 2018-08-31** arasındaki stabil dönem kullanılmalıdır.
2. **Grain Uyumsuzluğu Uyarısı:** `orders` ile `order_items` ve `order_payments` tablolarını doğrudan birleştirirken satır çoğalması (fan-out) riski vardır. Sipariş başına birden fazla ürün ve birden fazla ödeme kaydı bulunabilir. Gelir ve ödeme agregasyonları doğru grain seviyesinde ayrı hesaplanmalı, ardından sipariş anahtarıyla birleştirilmelidir. `price`, `freight_value` ve `payment_value` aynı metrikmiş gibi toplanmamalıdır.
3. **Müşteri Ayrımı:** Analizlerde `customer_id` (sipariş bazlı tekil) değil, `customer_unique_id` (gerçek tekil müşteri) baz alınmalıdır.

---

## 4. Mimari

### 4.1 Tarihsel Veri Yükleme Akışı
CSV dosyaları ilk yüklemede PostgreSQL'in Bronze katmanına alınır.

```text
Olist CSV files
      │
      ▼
Python Bulk Ingestion (COPY / chunksize)
      │
      ▼
PostgreSQL: bronze schema
      │
      ▼
Validation + Cleaning + Standardization
      │
      ▼
PostgreSQL: silver schema
      │
      ▼
SQL Aggregations / Analytical Marts (Star Schema)
      │
      ▼
PostgreSQL: gold schema
```

### 4.2 Simüle Edilmiş Gerçek Zamanlı Akış

```text
Historical Orders (Silver orders tablosu veya CSV)
      │
      ▼
Python Kafka Producer
      │
      ▼
Kafka Topic: orders.events
      │
      ▼
Python Kafka Consumer
      ├── Validate event schema
      ├── Deduplicate by event_id (Idempotent write)
      └── Write to PostgreSQL
      │
      ▼
PostgreSQL: streaming.order_events
      │
      ▼
FastAPI / Streamlit Real-Time Monitoring
```

### 4.3 Uygulama Akışı ve Mimari Esneklik (Fallback)
- **Varsayılan Mimari:** `PostgreSQL (Gold/Streaming)` $\rightarrow$ `FastAPI` $\rightarrow$ `Streamlit Dashboard`.
- **Zaman Kısıtı / B Planı (Fallback Kuralı):** 7 günlük geliştirme sürecinde FastAPI entegrasyonu dashboard ilerlemesini geciktirirse; Streamlit'in doğrudan SQLAlchemy ile PostgreSQL Gold ve Streaming şemalarına bağlanması mimari bir alternatif olarak kabul edilir. Ajan, önce çekirdek veri akışını bitirmeli, API katmanını darboğaz haline getirmemelidir.

---

## 5. Veri Katmanları ve Şema Tasarımı (Medallion Architecture)

PostgreSQL içinde 4 ayrı şema oluşturulacaktır:

- `bronze`: Kaynağa yakın ham tablolar.
- `silver`: Temizlenmiş, tipleri düzeltilmiş ve doğrulanmış tablolar.
- `gold`: Dashboard ve iş analitiği için hazır boyut/olgu tabloları ve analitik veri mart'ları.
- `streaming`: Kafka üzerinden tüketilen olaylar ve loglar.

### Bronze Katmanı
Ham tablolar oluşturulurken kaynak kolonlar korunur. Satır bazında tek tek insert yerine `COPY` komutu veya `pandas.to_sql(method='multi', chunksize=5000)` kullanılarak hızlı toplu yükleme (bulk load) yapılmalıdır.

### Silver Katmanı
- Temizlenmiş tablolar: `orders`, `customers`, `order_items`, `products`, `payments`, `reviews`.
- Kolon isimleri standart `snake_case` olmalıdır.
- Tarih kolonları `TIMESTAMP` tipine dönüştürülmelidir.
- Eksik veya tutarsız kayıtlar işaretlenmeli veya filtrelenmelidir.

### Gold Katmanı (Star Schema / Marts)
- `fact_orders`: Sipariş grain'inde metrikler (tutar, kargo, teslimat süresi vb.).
- `fact_order_items`: Sipariş kalemi bazında ürün ve fiyat detayları.
- `dim_customers`: Müşteri boyut tablosu (`customer_unique_id`).
- `dim_products`: Ürün boyut tablosu (kategori çevirileri ile).
- `mart_sales_daily`: Günlük ciro, sipariş adedi ve ortalama sepet değeri.
- `mart_category_performance`: Kategori bazlı gelir ve hacim.
- `mart_delivery_performance`: Teslimat süreleri, gecikme oranları ve müşteri memnuniyet puanları.
- `mart_customer_rfm`: RFM skorları ve segment etiketleri.

### Streaming Katmanı
`streaming.order_events` tablosu:
- `event_id` (UUID veya deterministik ID) — **PRIMARY KEY / UNIQUE**
- `order_id` (VARCHAR)
- `customer_id` (VARCHAR)
- `event_type` (VARCHAR)
- `event_timestamp` (TIMESTAMP)
- `payload` (JSONB)
- `consumed_at` (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)

---

## 6. Kafka Tasarımı

### Altyapı Notu
- Yerel sistem kaynaklarını korumak ve ZooKeeper bağımlılığını kaldırmak adına **Kafka KRaft modu** (`apache/kafka:3.7.0`) veya hafif C++ alternatifi **Redpanda** (`docker.redpanda.com/redpandadata/redpanda:latest`) kullanılacaktır. Docker imaj sürümü sabitlenmeli, `latest` etiketi kontrolsüz kullanılmamalıdır.

### Topic'ler
- **MVP:** `orders.events`
- **İsteğe Bağlı / DLQ:** `orders.dlq` (Hatalı/bozuk formatlı mesajlar için Dead Letter Queue)

### Event JSON Sözleşmesi
```json
{
  "event_id": "c56a4180-65aa-42ec-a945-5fd21dec0538",
  "event_type": "order_created",
  "order_id": "e481f51cbdc54678b7cc49136f2d6af7",
  "customer_id": "9ef432eb6251297304e76186b10a928d",
  "event_timestamp": "2017-10-02T10:56:33",
  "source": "olist_historical_replay",
  "payload": {
    "order_status": "delivered",
    "order_purchase_timestamp": "2017-10-02T10:56:33"
  }
}
```

### Teslimat Semantiği
İlk sürümde **at-least-once** teslimat ve veritabanında `event_id` üzerinden **idempotent write** (`ON CONFLICT (event_id) DO NOTHING`) uygulanacaktır. Kesinlikle "exactly-once" iddiasında bulunulmayacaktır.

---

## 7. ETL Gereksinimleri

- ETL kodları Jupyter Notebook içinde bırakılmamalı; modüler Python script'leri (`extract.py`, `transform.py`, `validation.py`, `load.py`) olarak yazılmalıdır.
- Veritabanı kimlik bilgileri `.env` dosyasından okunmalıdır.
- Parametreli SQL ve güvenli ORM/bağlantı metotları kullanılmalıdır (SQL Injection engeli).
- Hata veren ve null olan kayıtlar loglanmalıdır.

---

## 8. Analitik Kapsamı ve İş Mantığı

### 8.1 Satış Performansı
- Toplam Gelir (Total Revenue - Sadece onaylanmış/teslim edilmiş siparişler).
- Sipariş Sayısı, Ortalama Sepet Değeri (AOV - Average Order Value).
- Zaman serisi trendleri (aylık/günlük).
- Ödeme yöntemi dağılımı ve iptal oranları.

### 8.2 Müşteri Analitiği (RFM ve K-Means)
- **Recency:** Referans tarihe göre son alışverişten geçen gün.
- **Frequency:** `customer_unique_id` başına sipariş sayısı.
- **Monetary:** Toplam harcama tutarı.
- K-Means kümeleme uygulanacaksa: RFM değerleri log-dönüşümü ve standartlaştırma işlemine tabi tutulmalı, küme sayısı (K) silhouette skoru veya elbow yöntemiyle gerekçelendirilmeli, küme isimleri mantıksal olarak verilmelidir.

### 8.3 Teslimat Analitiği
- Satın almadan teslimata geçen süre (gün).
- Tahmini teslimat tarihi ile gerçekleşen teslimat farkı (gecikme gün sayısı).
- Gecikme oranı (Late delivery rate) ve gecikmelerin inceleme puanlarına (Review score) etkisi.
- Eksik teslim tarihi olan veya negatif çıkan hatalı veriler filtrelenmelidir.

### 8.4 Talep Tahmini (Demand Forecasting) — P1 Kapsamında
- **Kural:** P0 (Veri akışı, veritabanı, dashboard) tamamlanmadan forecasting koduna geçilmeyecektir.
- Günlük sipariş adedi için önce basit bir Moving Average baseline'ı kurulmalı, ardından Random Forest denenmelidir.
- Veri sızıntısını (data leakage) engellemek için zaman bazlı train/test ayrımı yapılmalıdır.

---

## 9. FastAPI Gereksinimleri

- `GET /api/health`: Servis ve DB bağlantı durumu kontrolü.
- `GET /api/sales/overview`: Temel KPI kartları verisi.
- `GET /api/sales/trends`: Satış trendleri zaman serisi.
- `GET /api/products/top`: En çok satan kategoriler/ürünler.
- `GET /api/delivery/performance`: Teslimat ve gecikme metrikleri.
- `GET /api/stream/status`: Kafka consumer metrikleri ve son gelen event logları.
- Pydantic modelleriyle schema validasyonu ve tip güvenliği sağlanmalıdır.

---

## 10. Streamlit Dashboard

Sayfa Hiyerarşisi:
1. **Overview (Yönetici Özeti):** Gelir, sipariş, sepet ortalaması KPI'ları ve satış trendleri.
2. **Customer & Segmentation:** RFM segmentleri ve dağılım grafikleri.
3. **Delivery & Operations:** Teslimat süreleri, gecikme oranları ve memnuniyet ilişkisi.
4. **Streaming Monitor (Kafka Canlı İzleme):** Kuyruktan akan event sayısı, saniyelik hacim ve son işlenen JSON event tablosu.

*(Not: Sayfalarda verinin tarihsel Olist verisi olduğu ve Kafka akışının bir replay simülasyonu olduğu şeffaf biçimde bir uyarı banner'ı ile gösterilmelidir.)*

---

## 11. Docker Yapılandırması

`docker-compose.yml` şu servisleri içerecektir:
- `postgres`: Port 5432, kalıcı volume.
- `kafka` (veya `redpanda`): Mesaj kuyruğu.
- `consumer`: Kafka'yı dinleyip DB'ye yazan arka plan servisi.
- `api`: FastAPI uygulaması (Port 8000).
- `dashboard`: Streamlit arayüzü (Port 8501).
- `producer`: `--profile replay` ile manuel veya parametreyle başlatılabilir script.

**Kural:** Container içi bağlantılarda asla `localhost` kullanılmamalı, Docker servis isimleri (`postgres`, `kafka` vb.) kullanılmalıdır.

---

## 12. Depo Dosya Yapısı

```text
retailpulse/
├── data/
│   └── raw/                    # Olist CSV'leri (Git'e eklenmez)
├── ingestion/
│   ├── producer.py             # Kafka event producer
│   └── consumer.py             # Kafka idempotent consumer
├── etl/
│   ├── extract.py              # CSV bulk ingestion
│   ├── transform.py            # Silver dönüşümleri
│   ├── validation.py           # Veri kalite testleri
│   └── load.py                 # Gold katmanı yüklemeleri
├── analytics/
│   ├── sales_analysis.py
│   ├── customer_analysis.py
│   └── delivery_analysis.py
├── api/
│   ├── main.py
│   ├── database.py
│   ├── schemas/
│   └── routes/
├── dashboard/
│   ├── app.py
│   └── pages/
├── database/
│   ├── 01_bronze.sql
│   ├── 02_silver.sql
│   └── 03_gold.sql
├── tests/
│   ├── test_etl.py
│   └── test_consumer.py
├── docker-compose.yml
├── Dockerfile.api
├── Dockerfile.dashboard
├── Dockerfile.consumer
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── TASKS.md
└── PROJECT_SPEC.md
```

---

## 13. Yedi Günlük Geliştirme Planı

- **Gün 1 — Veri Keşfi & PostgreSQL:** Repo kurulumu, Olist verilerinin incelenmesi, Bronze tablolarının oluşturulması ve bulk ingestion ile yüklenmesi.
- **Gün 2 — Docker & Kafka:** Docker Compose ile PostgreSQL ve Kafka/Redpanda'nın kurulması, producer ve consumer script'lerinin yazımı, idempotent veri yazımının doğrulanması.
- **Gün 3 — ETL & Veri Modelleme:** Silver ve Gold şemalarının kurulması, Star-Schema tablolarının oluşturulması, temel analitik view'ların hazırlanması.
- **Gün 4 — Analitik & Görselleştirme:** Satış, teslimat ve RFM müşteri analiz fonksiyonlarının yazılması, veri kalite kontrollerinin yapılması.
- **Gün 5 — Dashboard & Entegrasyon:** Streamlit arayüzünün kurulması, grafiklerin Plotly ile hazırlanması, streaming monitör ekranının eklenmesi (API entegrasyonu veya fallback doğrudan DB bağlantısı).
- **Gün 6 — Uçtan Uca Test & Dockerize Etme:** Servislerin Dockerize edilmesi, `pytest` ile temel testlerin çalıştırılması, temiz ortamda `docker compose up` testi.
- **Gün 7 — Dokümantasyon & Sunum:** `README.md` tamamlanması, mimari şemasının çizilmesi, sunum slaytlarının ve demo akışının hazırlanması.

---

## 14. Öncelik Matrisi (Önem Sırası)

### P0 (Kritik - Olmazsa Olmaz)
- PostgreSQL Medallion katmanları (Bronze/Silver/Gold)
- Hızlı veri yükleme (Bulk ingestion)
- Kafka producer & idempotent consumer akışı
- SQL analitik mart'ları (Satış, Teslimat)
- Çalışan Streamlit dashboard'u
- Docker Compose entegrasyonu
- Detaylı README ve çalışan demo

### P1 (Zaman Kalırsa)
- FastAPI servis katmanı
- RFM K-Means kümeleme
- Demand forecasting modeli
- Dead Letter Queue (DLQ)

### P2 (Kapsam Dışı)
- Spark, Airflow, Kubernetes, Bulut ortamı, Çoklu frontend.

---

## 15. Kodlama Ajanı İçin Kesin Çalışma Talimatları

1. **Önce Oku ve Planla:** Mevcut depoyu ve bu şartnameyi baştan sona oku. Kullanıcı onayı almadan kod yazmaya başlama.
2. **Kapsamı Koruma Kuralı:** P0 maddeleri eksiksiz çalışmadan ve test edilmeden P1 maddelerine (özellikle Scikit-learn modellerine) geçiş yapma.
3. **Varsayımda Bulunma:** Olist veri setinde olmayan kolonları uydurma. CSV başlıklarını okuyarak doğrula.
4. **Adım Adım Doğrulama:** Her adımdan sonra çalıştırılan komutları, testleri ve sonuçları raporla. Hata gizleme.
5. **Handoff Disiplini:** Her aşama tamamlandığında yapılanları, etkilenen dosyaları ve bir sonraki tek adımı bildir.

---

## 16. Başlangıç Komutu (Ajana Verilecek İlk Mesaj)

> Bu depoda RetailPulse projesini geliştireceğiz. Önce `PROJECT_SPEC.md` dosyasını ve mevcut repo yapısını incele. Henüz kod yazma.
>
> İlk olarak:  
> 1. Mevcut dosyaları ve ortamı kontrol et.  
> 2. Proje gereksinimlerini anladığını kısa şekilde özetle.  
> 3. 7 günlük planı P0/P1 önceliklerine göre uygulanabilir küçük adımlara böl.  
> 4. `TASKS.md` ve `DECISIONS.md` için başlangıç taslağı oluştur.  
>
> Ben onay verdikten sonra yalnızca Gün 1 görevlerinden başlayacağız. Kapsamı genişletme ve veri setinde olmayan kolonları varsayma.