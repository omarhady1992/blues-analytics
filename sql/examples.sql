-- Example queries to practise SQL on data/blues.db
-- Open data/blues.db in any SQLite client (DB Browser for SQLite, the VS Code SQLite extension) or use pandas.read_sql

-- 1. Season table per player (uses the view defined in pipeline/schema.sql)
SELECT * FROM v_player_season ORDER BY minutes DESC;

-- 2. Results with xG difference, newest first
SELECT m.kickoff_local, m.competition, m.opponent, m.goals_for || '-' || m.goals_against AS score,
       ROUND(c.xg - o.xg, 2) AS xg_diff
FROM matches m
JOIN team_match_stats c ON c.match_id = m.match_id AND c.side = 'chelsea'
JOIN team_match_stats o ON o.match_id = m.match_id AND o.side = 'opponent'
ORDER BY m.kickoff_utc DESC;

-- 3. Who over/under-performs xG? (goals minus xG, min 3 shots)
SELECT p.name, SUM(s.goals) AS goals, ROUND(SUM(s.xg), 2) AS xg, ROUND(SUM(s.goals) - SUM(s.xg), 2) AS diff
FROM player_match_stats s JOIN players p USING (player_id)
GROUP BY p.player_id HAVING SUM(s.shots) >= 3 ORDER BY diff DESC;

-- 4. Shots by situation (Understat, PL only)
SELECT situation, COUNT(*) AS shots, SUM(result = 'Goal') AS goals, ROUND(SUM(xg), 2) AS xg
FROM shots WHERE source = 'understat' AND side = 'chelsea' GROUP BY situation ORDER BY xg DESC;

-- 5. Joining sources: every id we know for one player
SELECT p.name, si.source, si.source_id
FROM players p JOIN source_ids si ON si.entity_type = 'player' AND si.entity_id = p.player_id
WHERE p.name LIKE '%Palmer%';

-- 6. Build-up & pressing by match vs Chelsea's season average (PPDA: Understat, PL only; NULL = n/a)
WITH c AS (SELECT * FROM team_match_buildup WHERE side = 'chelsea'),
     avg AS (SELECT AVG(ppda) AS ppda, AVG(long_ball_share) AS lb, AVG(gk_long_share) AS gk FROM c)
SELECT m.kickoff_utc, m.opponent, m.competition,
       c.ppda, ROUND(c.ppda - avg.ppda, 2)                  AS ppda_vs_avg,
       o.ppda                                               AS opponent_ppda,
       ROUND(100 * c.long_ball_share, 1)                    AS long_ball_pct,
       ROUND(100 * c.gk_long_share, 1)                      AS gk_long_pct,
       ROUND(100 * (c.gk_long_share - avg.gk), 1)           AS gk_long_pct_vs_avg,
       c.goal_kicks, c.final_third_entries, c.line_breaking_passes
FROM c CROSS JOIN avg
JOIN matches m USING (match_id)
JOIN team_match_buildup o ON o.match_id = c.match_id AND o.side = 'opponent'
ORDER BY m.kickoff_utc;
