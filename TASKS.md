# RetailPulse — 7 Günlük Görev Planı

Durumlar: BEKLEMEDE / AKTİF / TAMAMLANDI

## Gün 1 — Veri Keşfi ve PostgreSQL (P0)
- [x] Depo yapısını ve dokuz `data/raw/` CSV dosyasını doğrula; başlıkları ve temel veri özelliklerini incele. — **TAMAMLANDI**
- [x] PostgreSQL 16 için Bronze şema/tablo tasarımını CSV başlıklarına göre hazırla. — **TAMAMLANDI**
- [x] CSV dosyalarını Bronze tablolarına bulk ingestion ile yükle ve satır sayılarını doğrula. — **TAMAMLANDI** (PostgreSQL host portu 5434; `python etl/extract.py` COPY yüklemesi tamamlandı ve altı tablonun COUNT(*) değerleri doğrulandı.)

İlk adım keşif sayımları: orders 99,441; customers 99,441; order_items 112,650; products 32,951; order_payments 103,886; order_reviews 99,224. DDL kolonları altı CSV'nin header'larıyla eşleşti ve `etl/extract.py` syntax kontrolü geçti.

Gün 1 ingestion sonucu: Host portu 5434'e alındı (`5434:5432`) ve `.env` ile `.env.example` içindeki `DB_PORT=5434` olarak güncellendi. `etl/extract.py`, psycopg `write_row()` ile uyumlu PostgreSQL text COPY moduna geçirildi; boş hücreler NULL olarak aktarılıyor ve CSV header'ı atlanıyor. `python etl/extract.py` tamamlandı; doğrudan DB COUNT(*) sonuçları: orders 99,441; customers 99,441; order_items 112,650; products 32,951; order_payments 103,886; order_reviews 99,224.

Silver dönüşüm sonucu: Silver satır sayıları — orders 99,092; customers 99,441; order_items 112,279; products 32,951; order_payments 103,520; order_reviews 98,879. Tarih filtresinde 99,092 sipariş dahil, 349 sipariş hariç tutuldu. Null anahtar kontrolleri ve negatif fiyat/kargo/ödeme kontrollerinin tamamı 0; tarih kontrollerinde 166 `order_delivered_carrier_date` değeri sipariş satın alma zamanından önce bulundu, kayıtlar raporda görünür bırakıldı.

## Gün 2 — Docker ve Kafka (P0)
- [x] PostgreSQL ve Kafka KRaft servislerini Docker Compose ile yapılandır. — **TAMAMLANDI** (`apache/kafka:3.7.0`; host `localhost:9092`, Compose içi `kafka:9093`; broker healthcheck healthy.)
- [x] Sipariş olaylarını yayınlayan Kafka producer'ı ve olay sözleşmesini oluştur. — **TAMAMLANDI** (`ingestion/producer.py`; Silver siparişlerinden deterministik UUID5 event ID ile `orders.events` yayınlıyor.)
- [x] Idempotent yazımlı consumer akışını kur ve doğrula. — **TAMAMLANDI** (`ON CONFLICT (event_id) DO NOTHING`; 200 ilk insert, aynı 200 tekrarında 200 duplicate skip ve DB toplamı 200.)

Gün 2 Kafka doğrulaması: `database/04_streaming.sql` uygulandı; Kafka 3.7.0 KRaft healthy. İlk replay'de producer 200 mesaj teslim etti ve consumer 200 kayıt ekledi. Aynı 200 deterministik event ikinci kez yayınlandığında consumer 200 duplicate'i atladı; `streaming.order_events` COUNT(*) = 200 ve COUNT(DISTINCT event_id) = 200.

## Gün 3 — ETL ve Veri Modelleme (P0)
- [x] Silver şemasını ve temizlenmiş tabloları kur; tipleri, adları ve kalite kurallarını uygula. — **TAMAMLANDI** (`02_silver.sql`, `etl/transform.py`, `etl/validation.py` eklendi; satır sayıları ve kalite kontrolleri raporlandı.)
- [x] Gold şemasında fact/dimension tablolarını ve gerekli analitik view/mart'ları oluştur. — **TAMAMLANDI** (`03_gold.sql` ve `etl/load.py` ile iki dimension, iki fact ve dört mart yüklendi; ciro toplamı Silver ile eşleşti.)
- [x] Analitik tarih aralığı filtresini uygula ve sipariş/kalem/ödeme grain'lerini koru. — **TAMAMLANDI** (Silver siparişleri 2017-01-01–2018-08-31 aralığına göre seçildi; bağlı kalem ve ödeme kayıtları sipariş grain'iyle tutuldu.)

Gold yükleme/doğrulama sonucu: dim_customers 96,096; dim_products 32,951; fact_orders 99,092; fact_order_items 112,279; mart_sales_daily 602; mart_category_performance 74; mart_delivery_performance 533; mart_customer_rfm 93,106. `SUM(gold.fact_orders.total_product_amount)` = `SUM(silver.order_items.price)` = 13,541,712.78; fark 0.00 ve kuruş hassasiyetinde eşleşme sağlandı.

## Gün 4 — Analitik ve Veri Kalitesi (P0)
- [x] Satış, teslimat ve müşteri analizi için temel fonksiyonları hazırla. — **TAMAMLANDI** (Gold satış, teslimat ve RFM mart'ları Streamlit sayfalarına bağlandı.)
- [ ] Veri kalite kontrollerini ve temel ETL/consumer testlerini ekle. — **BEKLEMEDE**
- [ ] Günlük satış, kategori ve teslimat metriklerini doğrula. — **BEKLEMEDE**

## Gün 5 — Dashboard ve Entegrasyon (P0)
- [x] Streamlit dashboard iskeletini ve tarihsel veri/replay açıklamasını oluştur. — **TAMAMLANDI** (`dashboard/app.py`; tarih filtresi ve tarihsel Olist/Kafka replay banner'ı.)
- [x] Yönetici özeti, satış trendi, müşteri ve teslimat görsellerini bağla. — **TAMAMLANDI** (KPI'lar, Plotly trend/kategori, RFM ve eyalet teslimat görselleri.)
- [x] Streaming monitör görünümünü PostgreSQL akışına bağla; API gerekirse P1 kapsamında değerlendir. — **TAMAMLANDI** (Toplam event, son 10 kayıt, JSON görünümü ve yenileme düğmesi.)

Dashboard doğrulaması: Streamlit `http://localhost:8501` adresinde çalışıyor ve health endpoint'i `ok` döndürüyor. Streamlit multipage test koşusunda ana sayfa ile Overview, Customer and Delivery ve Streaming Monitor sayfalarının hiçbirinde exception oluşmadı.

## Gün 6 — Uçtan Uca Çalıştırma (P0)
- [ ] Uygulama servisleri için Docker yapılandırmasını tamamla. — **BEKLEMEDE**
- [ ] Temel testleri ve temiz ortamda uçtan uca Compose çalıştırmasını doğrula. — **BEKLEMEDE**
- [ ] Çalışan veri yükleme, analitik ve dashboard akışını gözden geçir. — **BEKLEMEDE**

## Gün 7 — Dokümantasyon ve Demo (P0)
- [ ] README'yi kurulum, kullanım, veri kapsamı ve mimariyle tamamla. — **BEKLEMEDE**
- [ ] Mimari şema, sunum ve demo akışını hazırla. — **BEKLEMEDE**
- [ ] Teslim kapsamını ve P0 tamamlanma durumunu gözden geçir. — **BEKLEMEDE**

## P1 — P0 tamamlandıktan sonra / zaman kalırsa
- [x] FastAPI servis katmanını ve temel analitik/sağlık uçlarını ekle. — **TAMAMLANDI** (`api/` modüler servis, SQLAlchemy DB session, Pydantic response modelleri, CORS ve health/KPI/segment/streaming uçları eklendi; Compose'a servis eklenmedi.)
API doğrulaması: uvicorn `0.0.0.0:8000` üzerinde çalışıyor; `/health`, şartname uyumlu `/api/health`, `/api/v1/metrics/kpis`, `/api/v1/customers/segments` ve `/api/v1/streaming/stats` uçlarının tümü HTTP 200 JSON döndürdü.
- [x] `customer_unique_id` temelinde RFM skorları ve gerekçeli K-Means segmentasyonu ekle. — **TAMAMLANDI** (`log1p` + StandardScaler, k=4 K-Means ve profile-based segment adları `gold.mart_customer_segments` tablosuna yazıldı; Streamlit müşteri analitiğine donut ve segment karşılaştırma grafikleri eklendi.)
Müşteri segmentasyonu sonucu: `gold.mart_customer_segments` toplam 93,106 müşteri içeriyor. Silhouette(k=4, örneklem=5,000) = 0.3928. Dağılım: At Risk 37,260; Champions 2,789; Hibernating/Lost 36,214; Loyal Customers 16,843. Customer and Delivery sayfasındaki müşteri analitiği sekmesi 6 Plotly grafikle exception/error olmadan doğrulandı.

- [ ] P0 tamamlandıktan sonra günlük sipariş tahmininde moving-average baseline ve Random Forest karşılaştırması yap. — **BEKLEMEDE**
- [ ] İsteğe bağlı Kafka DLQ akışını ekle. — **BEKLEMEDE**
