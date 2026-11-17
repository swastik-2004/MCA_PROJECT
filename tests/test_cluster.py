"""Master-worker cluster: same results as sequential code, even when a worker crashes."""
from levelforge.cluster import SimCluster, make_tasks
from levelforge.generator import random_candidate
from levelforge.simulator import simulate


def test_cluster_matches_sequential_and_survives_a_crash():
    tasks = make_tasks(random_candidate(3).to_dict(), 20, base_seed=5)   # 60 playthroughs
    expected = [simulate(*t) for t in tasks]
    with SimCluster(2, chunk=4) as cluster:
        assert cluster.run_tasks(tasks) == expected
        cluster.chaos(1)                      # kill one worker part-way through the next job
        assert cluster.run_tasks(tasks) == expected
        assert cluster.failures == 1
        assert cluster.last_job["events"][0]["type"] == "worker_died"
        assert len(cluster.alive_workers()) == 2   # a replacement was started
