"""Camera capture from MARS robot via ROS2 topics.

The MARS cameras are managed by innate-os and exposed as ROS2 topics.
Direct /dev/video* access does NOT work — innate-os owns the hardware.

Main camera topic: /mars/main_camera/left/image_rect_color
Arm camera topic:  /mars/arm/image_raw
"""

import base64
import threading
import time

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge


MAIN_CAMERA_TOPIC = "/mars/main_camera/left/image_raw"
ARM_CAMERA_TOPIC = "/mars/arm/image_raw"


class MARSCamera(Node):
    """Subscribes to MARS camera ROS2 topic and provides latest frame."""

    def __init__(self, topic=MAIN_CAMERA_TOPIC):
        super().__init__("emotion_tracker_camera")
        self.bridge = CvBridge()
        self.latest_frame = None
        self._lock = threading.Lock()

        self.subscription = self.create_subscription(
            Image,
            topic,
            self._on_frame,
            10,
        )
        self.get_logger().info(f"Subscribed to {topic}")

        # spin in background thread so we don't block
        self._spin_thread = threading.Thread(target=self._spin, daemon=True)
        self._spin_thread.start()

    def _on_frame(self, msg):
        """Callback: convert ROS Image to OpenCV frame."""
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        with self._lock:
            self.latest_frame = frame

    def _spin(self):
        """Background spin to keep receiving frames."""
        rclpy.spin(self)

    def capture_frame(self):
        """Get the most recent camera frame. Blocks briefly if no frame yet."""
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with self._lock:
                if self.latest_frame is not None:
                    return self.latest_frame.copy()
            time.sleep(0.05)
        raise RuntimeError("No frame received from camera within 5 seconds")

    def frame_to_base64(self, frame):
        """Convert a frame to base64-encoded JPEG for the Gemini API."""
        _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buffer).decode("utf-8")

    def close(self):
        self.destroy_node()


def init_camera(topic=MAIN_CAMERA_TOPIC):
    """Initialize ROS2 and return a MARSCamera node."""
    if not rclpy.ok():
        rclpy.init()
    return MARSCamera(topic=topic)
