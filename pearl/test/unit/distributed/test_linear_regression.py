# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.
#

import unittest

import __manifest__  # FIXME: this is Meta-only

import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from pearl.utils.functional_utils.learning.linear_regression import LinearRegression


def train(rank: int, world_size: int) -> None:
    feature_dim = 3
    batch_size = 3

    dist.init_process_group(
        backend="nccl" if torch.cuda.is_available() else "gloo",
        init_method=f"tcp://localhost:29501?world_size={world_size}&rank={rank}",
    )

    linear_regression = LinearRegression(feature_dim=feature_dim)

    feature = torch.ones(batch_size, feature_dim, device=linear_regression.device)
    reward = feature.sum(-1)
    weight = torch.ones(batch_size, device=linear_regression.device)
    linear_regression.learn_batch(x=feature, y=reward, weight=weight)

    dist.barrier()
    if rank == 0:
        torch.save(linear_regression.state_dict(), "/tmp/final_model.pth")


build_mode_is_opt: bool = __manifest__.fbmake.get("build_mode", "") == "opt"


class TestLinearRegression(unittest.TestCase):
    @unittest.skipIf(
        build_mode_is_opt,
        "This test only works with opt mode",
    )
    def test_reduce_all(self) -> None:
        world_size = (
            torch.cuda.device_count() if torch.cuda.is_available() else mp.cpu_count()
        )
        feature_dim = 3
        batch_size = 3

        # train in multi process
        mp.spawn(train, args=(world_size,), nprocs=world_size)
        mp_state_dict = torch.load("/tmp/final_model.pth")

        # train in single process
        linear_regression = LinearRegression(feature_dim=feature_dim)
        feature = torch.ones(batch_size, feature_dim)
        reward = feature.sum(-1)
        weight = torch.ones(batch_size)
        for _ in range(world_size):
            linear_regression.learn_batch(x=feature, y=reward, weight=weight)

        sp_state_dict = linear_regression.state_dict()
        for k, v in mp_state_dict.items():
            self.assertTrue(torch.equal(v, sp_state_dict[k]))
