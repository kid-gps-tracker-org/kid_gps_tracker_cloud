#!/usr/bin/env python3
"""
Kid GPS Tracker CDK App
"""
import aws_cdk as cdk
from kid_gps_tracker.stack import KidGpsTrackerStack

app = cdk.App()

KidGpsTrackerStack(
    app,
    "KidGpsTrackerStack",
    env=cdk.Environment(
        account="904142936725",
        region="ap-northeast-1",
    ),
)

app.synth()
