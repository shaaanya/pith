# note-nothink-v5 (gemma4:e4b)

```json
{
 "variant": "note-nothink-v5",
 "model": "gemma4:e4b",
 "cases": 14,
 "mean_recall": 0.986,
 "blocking": 0,
 "commentary_total": 0,
 "invented_number_cases": 0,
 "mean_words": 123,
 "total_calls": 13,
 "total_seconds": 277.1
}
```

## twitch_reel  recall 1.0  blocking=False  15.7s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

30-day preparation plan for Twitch Payments Software Engineer role

## Steps

1. Figure out the tech stack by looking at older Twitch job postings and engineering blog articles.
2. Learn payments fundamentals, which are idempotency and database transactions, by reading Chapter 7 of Designing Data-Intensive Applications.
3. Do the Tour of Go and read Marc Brooker's writing on DynamoDB and Aurora DSQL.
4. Every morning practice system design on Devmaxx, focusing on the database questions.
5. Build a fishing tournament manager using Lambda, DynamoDB, SQS, and Step Functions.

## Facts

- Twitch posted an entry-level payments software engineer role with a salary range of $127K-$185K.
- The tech stack uses Go, DynamoDB, Lambda, SQS, and Step Functions.

## postgres_noisy_transcript  recall 1.0  blocking=False  11.3s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Postgres performance fixes

1. When creating an index, use CREATE INDEX CONCURRENTLY so that writes are not blocked.
2. Always run EXPLAIN (ANALYZE, BUFFERS) before and after changes to see the actual numbers.
3. Stop using OFFSET pagination because it gets slower the deeper you go.
4. Use keyset pagination where WHERE id > $last_id ORDER BY id LIMIT 50.

## podcast_brief_mention_intent  recall 1.0  blocking=False  16.0s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

**Why saved:** Saved for the Claude Code skill mentioned in the middle

Coding agents, code review, and burnout

## Relevant to why you saved this

- A Claude Code skill called systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.

## Facts

- The show discusses shipping faster with coding agents.
- Dana and Marcus agree to cap work in progress at 3 tasks.
- They also discuss how on call rotations should change when agents ship code at night.

## Claims

- Dana thinks the biggest win of using coding agents is fewer context switches.
- Marcus disagrees, saying review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- Dana believes burnout is the real risk with agents because the pace never drops.

## podcast_brief_mention_no_intent  recall 0.8  blocking=False  19.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Episode 41 discussion on shipping faster with coding agents

## Steps

1. systematic-debugging forces the agent to reproduce the bug and write down a hypothesis before touching any code.
2. The participants agreed to cap work in progress at 3 tasks.

## Facts

- The episode discusses shipping faster with coding agents.
- There is a Claude Code skill called systematic-debugging.
- Marcus blocks mornings for deep work and does no meetings before noon.
- They also discussed how on call rotations should change when agents ship code at night.

## Claims

- Dana thinks the biggest win is fewer context switches, not speed.
- Marcus disagrees, saying review time just moves to a different place.
- Dana says small pull requests still matter because reviewers still read linearly.
- Dana says burnout is the real risk with agents because the pace never drops.
- Marcus recommends the book Four Thousand Weeks by Oliver Burkeman for thinking about limits.

## docker_tutorial  recall 1.0  blocking=False  24.1s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Deploy a Flask app on a VPS with Docker

1. Create a Dockerfile starting from python 3.12 slim.
2. Copy requirements.txt and run pip install no cache dir.
3. Copy the app and set the command to gunicorn bound to 0.0.0.0 port 8000 with app:app.
4. Build the image with docker build -t flaskapp .
5. Run the container with docker run -d -p 80:8000 --env-file .env --restart unless stopped flaskapp.
6. Add the .env file to .gitignore because it needs DATABASE_URL and SECRET_KEY.
7. Check docker logs flaskapp if the container exits.
8. Put caddy in front for https so it gets the certificate automatically.
9. The caddyfile should contain just your domain and reverse_proxy localhost:8000.

## opinion_essay  recall 1.0  blocking=False  26.7s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Developer productivity metrics critique

## Facts

- At one company, commit counts per developer rose 40% within a quarter after being added to a dashboard.
- At that same company, shipped features per quarter fell from 11 to 8.
- Developers at that company split work into tiny commits and avoided hard refactors that produce a single large change.
- A one line fix to a payment bug can matter more than a month of churn.
- Pairing and review produce no commits for the reviewer.
- The median waiting time between review and deploy was 3 days.
- DORA metrics include deployment frequency, lead time for changes, change failure rate, and time to restore service.
- The author notes DORA metrics should be tracked per team, not per individual.
- The author notes that DORA metrics still carry the risk of gaming.

## Claims

- Counting commits to measure developer productivity is a mistake because of Goodhart's law.
- The author's first argument is that commits measure activity, not value.
- The author's second argument is that the metric punishes collaboration.
- The author's third argument is that commit counting hides the real constraint, which in the described cases was waiting time between review and deploy.
- Critics reply that some quantitative signal is needed for management.
- The author concedes this and suggests DORA metrics instead.

## Definitions

- Goodhart's law states that once a measure becomes a target, it stops being a good measure.

## news_numbers  recall 1.0  blocking=False  38.7s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Harbour Ferries Kestrel Route Suspension

## Facts

- Harbour Ferries suspended all sailings on the Kestrel route on Tuesday 14 October.
- The suspension was due to an inspection finding cracks in the hull of the MV Linnet.
- The company confirmed 212 passengers were on board when the cracks were reported on 9 October.
- Nobody was hurt when the cracks were reported.
- The MV Linnet was built in 1998.
- The Linnet carries up to 340 passengers.
- Transport minister Priya Anand stated the suspension would last at least 3 weeks.
- Priya Anand said the ferry operator would receive no compensation for lost fares.
- A union representative named Tom Reyes alleged that two earlier inspection reports in 2023 had flagged corrosion and were not acted on.
- Harbour Ferries denied the allegation and said the 2023 reports found only cosmetic wear.
- Replacement buses will run every 20 minutes from Wednesday.
- Replacement bus trips cost 4.50 pounds, which is the same as the ferry fare.

## Claims

- The claim regarding the earlier inspection reports has not been verified.

## web_table_article  recall 1.0  blocking=False  34.4s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Message Queue Selection Guide

## Steps

1. Pick Apache Kafka only if consumers must re-read history or if more than 100,000 messages per second are needed.
2. Pick Amazon SQS FIFO when order matters per customer.

## Facts

- Amazon SQS Standard has best effort ordering, no replay, a maximum message size of 256 KB, and no operational cost.
- Amazon SQS FIFO has strict per group ordering, no replay, a maximum message size of 256 KB, and no operational cost.
- Apache Kafka has strict per partition ordering, replay capability, a default maximum message size of 1 MB, and high operational cost.
- RabbitMQ has per queue ordering, no replay, a maximum message size of 128 MB, and medium operational cost.

## Claims

- The decision for most teams comes down to ordering guarantees and operational cost.
- The recommendation is to start with a managed queue unless replay is needed.

## Caveats

- Avoid RabbitMQ lazy queues for payloads near the 128 MB limit because memory pressure causes stalls.

## plain_note  recall 1.0  blocking=False  0.0s / 0 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Dentist Thu 3pm, bring insurance card. Ask about the night guard. Pick up Mira's inhaler refill before 6.

## promo_filler_reel  recall 1.0  blocking=False  16.2s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

My 5am routine

## Steps

1. The first hour after waking has no phone use.
2. The person drinks 500 ml of water.
3. The person does 10 minutes of mobility.
4. At six, the person writes for 45 minutes before anything else.

## Facts

- The person wakes at five.
- A cold shower is optional because the research on it is weak.

## incomplete_list  recall 1.0  blocking=False  8.7s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Ten habits of great engineers

## Steps

1. They write design docs before code.
2. They read the code of the tools they use.
3. They delete code happily.
4. They ask what problem are we solving before how.

## Facts

- There are ten habits of great engineers.

**Limits:** The remaining five habits are not provided in the source.

## ocr_config_screenshot  recall 1.0  blocking=False  29.8s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

**Why saved:** Settings to copy for the nginx rate limit

Nginx rate limiting settings

## Steps

1. A limit_req_zone is defined within the http block.
2. A location block is defined for /api/.
3. Inside the /api/ location, a limit_req is configured using zone=api.
4. The limit_req_status is set to 429.
5. The nginx configuration can be reloaded using the command sudo nginx -s reload.

## Facts

- The limit_req_zone uses $binary_remote_addr as the key.
- The zone is named api:10m.
- The rate specified for the zone is 5r/s.
- The limit_req configuration also includes burst=10 and nodelay.
- The zone size of 10m is approximately 160k IPs.

## Source text, exact
```
nginx.conf
http {
  limit_req_zone $binary_remote_addr zone=api:10m rate=5r/s;
  server {
    location /api/ {
      limit_req zone=api burst=10 nodelay;
      limit_req_status 429;
    }
  }
}
# 10m zone ~ 160k IPs
reload: sudo nginx -s reload
```

## paper_results  recall 1.0  blocking=False  20.4s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

WindowSparse attention pattern performance

## Facts

- On the LongDocQA benchmark, WindowSparse reaches 71.4 F1.
- Full attention reaches 68.9 F1 on the LongDocQA benchmark.
- WindowSparse uses 3.1x less memory at 16k tokens compared to full attention.
- Memory at 16k tokens for full attention is 38.2 GB.
- Memory at 16k tokens for WindowSparse is 12.3 GB.
- Training used 64 A100 GPUs for 9 days.
- The improvement over full attention is within one standard deviation on three of the 5 tasks.
- WindowSparse underperforms on tasks requiring long-range exact copy, dropping to 41.0 F1 on the SyntheticCopy task.
- Full attention reaches 88.5 F1 on the SyntheticCopy task.
- The evaluation was not conducted beyond 32k tokens.

## Definitions

- WindowSparse is a sparse attention pattern that combines local windows of 512 tokens with 8 global tokens per layer.

## correction_in_talk  recall 1.0  blocking=False  15.3s / 1 calls
missing(critical)=[] forbidden=[] invented=[] commentary=0

Database sharding strategy change

## Steps

1. The strategy was switched to sharding by document id hash.

## Facts

- The search cluster originally had 8 nodes.
- Sharding by customer handled 2,000 queries per second.
- One huge customer made one shard hot.
- P99 latency reached 900 ms with sharding by customer.
- After the switch, p99 dropped to 120 ms.
- The cluster was moved to 12 nodes after the switch.

## Claims

- One lesson is not to shard on a key whose distribution is not controlled.
