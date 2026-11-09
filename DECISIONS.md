# RetailPulse — Başlangıç Mimari Kararları

- İlişkisel veri deposu PostgreSQL 16 olacaktır.
- Olay akışı ZooKeeper gerektirmeyen Kafka KRaft modunda çalışacaktır.
- PostgreSQL'de ham, temizlenmiş ve analitik katmanlar sırasıyla `bronze`, `silver` ve `gold` Medallion şemalarında tutulacaktır.
- Varsayılan analitik tarih aralığı 2017-01-01 ile 2018-08-31 (dahil) olacaktır.
- Silver dönüşümünde siparişler bu tarih aralığına göre filtrelenir ve bağlı kalem, ödeme ve inceleme satırları yalnızca kapsamdaki siparişlerle aktarılır.
- `silver.customers` tablosu hem `customer_id` hem de `customer_unique_id` alanlarını korur ve ZIP prefix'ini beş karakterli metin olarak saklar.
- Ürün uzunluk alanlarının kaynak yazım hataları Silver şemasında `product_name_length` ve `product_description_length` olarak standartlaştırılır.
- Kafka 3.7.0 KRaft broker'ı host istemcilerine `localhost:9092`, Compose içi istemcilere `kafka:9093` adresini duyurur.
- Order replay event ID'leri aynı sipariş için tekrar üretilebilir olması amacıyla UUID5 ile deterministik oluşturulur ve PostgreSQL consumer'ı `event_id` üzerinden idempotent insert uygular.
- Streaming event tüketimi at-least-once kabul edilir; `streaming.order_events.event_id` birincil anahtarı tekrar yazımları engeller.
- Gold `fact_orders` grain'i sipariş, `fact_order_items` grain'i sipariş kalemidir; kalem ve ödeme tutarları sipariş anahtarında ayrı ayrı agregalanıp birleştirilir.
- Satış, kategori ve müşteri RFM gelir metrikleri `approved` veya `delivered` durumundaki siparişleri kullanır; ciro ürün bedelidir, ödeme ve kargo toplamları ayrı tutulur.
- RFM recency referans tarihi Gold sipariş verisindeki en ileri satın alma tarihinin ertesi günüdür; bu nedenle geçmiş dönem segmentleri tekrarlanabilir kalır.
- Streamlit dashboard, FastAPI olmadan SQLAlchemy 2 ve psycopg üzerinden PostgreSQL'e doğrudan bağlanır; yerel host ayarı `.env` içindeki `DB_HOST=localhost` ve `DB_PORT=5434` değerlerini kullanır.
- Satış, kategori ve teslimat görselleri genel tarih filtresini uygular; sabit dönemli RFM martı tarih filtresinden bağımsız gösterilir.
- Dashboard tüm sayfalarda Olist verisinin tarihsel, Kafka olaylarının ise replay simülasyonu olduğunu açıkça belirtir.
- Customer RFM segmentasyonu `recency`, `frequency` ve `monetary` üzerinde `log1p` ve StandardScaler sonrası deterministik `k=4` K-Means ile çalıştırılır; silhouette skoru 5,000 örneklemde raporlanır.
- K-Means'in sayısal cluster etiketleri ham RFM profil sıralamasına göre Champions, Loyal Customers, At Risk ve Hibernating/Lost iş adlarına eşlenir; sonuçlar `gold.mart_customer_segments` tablosuna transaction içinde yenilenir.
