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
