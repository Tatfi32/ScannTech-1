import struct
from datetime import datetime
from distutils.dir_util import copy_tree
from pathlib import Path
import shutil
import numpy as np
import pandas as pd


class PointReader:
    def __init__(self, data_path):
        self.data_path = Path(data_path) / 'data'
        self.pcap_path = self.data_path / 'pcap'
        self.pcap_files = [x for x in self.pcap_path.glob('*.*') if x.is_file()]
        self.LASER_ANGLES = [-15, 1, -13, -3, -11, 5, -9, 7, -7, 9, -5, 11, -3, 13, -1, 15]
        self.NUM_LASERS = 16
        self.DISTANCE_RESOLUTION = 0.002
        self.ROTATION_MAX_UNITS = 36000

        self.df = pd.DataFrame({'X': [], 'Y': [], 'Z': [], 'D': [], 'azimuth': [], 'laser_id': [],
                                'first_timestamp': [], 'pcap_num': []})
        self.azimuth_bin = 1000
        self.first_timestamp = None
        self.factory = None

    def read_pcap(self, file_number, azimuth_bin=100):
        if azimuth_bin != self.azimuth_bin:
            self.azimuth_bin = azimuth_bin
        self.get_pcap_data(file_number)
        return self.df

    def get_pcap_data(self, file_number):
        print('Getting pcap data...')
        pcap_file = str(self.pcap_files[int(file_number) - 1])
        pcap_data = open(pcap_file, 'rb').read()
        pcap_data = pcap_data[24:]
        for offset in range(0, int(len(pcap_data)), 1264):
            if (len(pcap_data) - offset) < 1264:
                break

            ''' current packet 1264 inclide 16 timeinfo '''
            cur_packet = pcap_data[offset + 16: offset + 16 + 42 + 1200 + 4 + 2]

            cur_data = cur_packet[42:]
            self.first_timestamp, self.factory = struct.unpack_from("<IH", cur_data, offset=1200)
            assert hex(self.factory) == '0x2237', 'Error mode: 0x22=VLP-16, 0x37=Strongest Return'
            seq_index = 0
            for seq_offset in range(0, 1100, 100):
                self.seq_processing(cur_data, seq_offset, seq_index, self.first_timestamp, int(file_number) - 1)
        print('End processing pcap file...')

    def seq_processing(self, data, seq_offset, seq_index, first_timestamp, pcap_num):
        flag, first_azimuth = struct.unpack_from("<HH", data, seq_offset)
        step_azimuth = 0
        assert hex(flag) == '0xeeff', 'Flag error'
        for step in range(2):
            if step == 0 and seq_index % 2 == 0 and seq_index < 22:
                flag, third_azimuth = struct.unpack_from("<HH", data, seq_offset + 4 + 3 * 16 * 2)
                assert hex(flag) == '0xeeff', 'Flag error'
                if third_azimuth < first_azimuth:
                    step_azimuth = third_azimuth + self.ROTATION_MAX_UNITS - first_azimuth
                else:
                    step_azimuth = third_azimuth - first_azimuth

            arr = struct.unpack_from('<' + "HB" * self.NUM_LASERS, data, seq_offset + 4 + step * 3 * 16)

            for i in range(self.NUM_LASERS):
                azimuth = first_azimuth + (step_azimuth * (55.296 / 1e6 * step + i * 2.304 / 1e6)) / (2 * 55.296 / 1e6)
                if azimuth > self.ROTATION_MAX_UNITS:
                    azimuth -= self.ROTATION_MAX_UNITS

                x, y, z = self.calc_real_val(arr[i * 2], azimuth, i)
                # azimuth_time = (55.296 / 1e6 * step + i * (2.304 / 1e6)) + first_timestamp
                new_row = pd.Series(
                    [x, y, z, arr[i * 2 + 1], round(azimuth * 1.0 / self.azimuth_bin), i, first_timestamp, pcap_num],
                    index=self.df.columns)
                self.df = self.df.append(new_row, ignore_index=True)
            seq_index += 1

    def calc_real_val(self, dis, azimuth, laser_id):
        r = dis * self.DISTANCE_RESOLUTION
        omega = self.LASER_ANGLES[laser_id] * np.pi / 180.0
        alpha = (azimuth / 100.0) * (np.pi / 180.0)
        x = r * np.cos(omega) * np.sin(alpha)
        y = r * np.cos(omega) * np.cos(alpha)
        z = r * np.sin(omega)

        return x, y, z


class PointProcessing:
    def __init__(self, data_path):
        self.data_path = data_path
        self.local_point_reader = PointReader(data_path=self.data_path)
        self.processed_pcap = None
        self.full_dataframe = pd.DataFrame()

    def get_all_points_by_timestamp(self, timestamp, pcap_index, azimuth_bin=100, azimuth=None):
        if pcap_index != self.processed_pcap:
            self.processed_pcap = pcap_index
            index_dataframe = self.local_point_reader.read_pcap(pcap_index, azimuth_bin)
            self.full_dataframe = pd.concat([self.full_dataframe, index_dataframe], ignore_index=True)

        if azimuth is not None:
            return self.full_dataframe[(self.full_dataframe['azimuth'] == azimuth) &
                                        [self.full_dataframe['first_timestamp'] == timestamp]]
        else:
            return self.full_dataframe[self.full_dataframe['first_timestamp'] == timestamp]
